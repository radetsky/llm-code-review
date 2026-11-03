"""
Measure the cost of the review engines on real changes from the git history.

The golden cases show quality on small, planted problems. This tool shows the
cost on real changes of different sizes: time, tokens, steps, budgets that
ended a review, fallbacks and the number of findings. There is no answer key,
so the tool cannot tell if a finding is right. Read the findings in runs.json.

Example:
    python -m evaluation.history --repo . --per-bucket 4

The tool sends the code of the repository to the LLM that you configure.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from config import ENGINES, ReviewConfig
from diff_parser import DiffParser
from evaluation.run_eval import RESULTS_DIR, ROOT, run_review
from monitor import percentile
from review_core import LLMReviewer

# Size classes: changed lines (added and removed) in files that the review reads.
BUCKETS = (
    ("small", 1, 40),
    ("medium", 41, 200),
    ("large", 201, 800),
    ("huge", 801, 10**9),
)
MAX_WINDOW = 12  # Most commits that one "window" sample joins.


@dataclass
class Sample:
    bucket: str
    base: str
    head: str
    commits: int
    files: int
    lines: int
    label: str


def bucket_of(lines: int) -> str | None:
    for name, low, high in BUCKETS:
        if low <= lines <= high:
            return name
    return None


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout


def diff_size(
    repo: Path, base: str, head: str, config: ReviewConfig
) -> tuple[int, int]:
    """Return (files, changed lines) of base...head for files that the review reads."""
    files = lines = 0
    for row in _git(repo, "diff", "--numstat", f"{base}...{head}").splitlines():
        added, removed, name = row.split("\t", 2)
        if added == "-" or not config.is_file_supported(name):
            continue  # A binary file or a file type that the review skips.
        files += 1
        lines += int(added) + int(removed)
    return files, lines


def list_commits(repo: Path, limit: int) -> list[str]:
    """Return the newest commits that have a parent, newest first. Merges are skipped."""
    out = _git(repo, "log", "--no-merges", "--format=%H %P", f"-n{limit}")
    return [row.split()[0] for row in out.splitlines() if len(row.split()) > 1]


def pick_samples(
    repo: Path, commits: list[str], per_bucket: int, config: ReviewConfig
) -> list[Sample]:
    """Pick changes of each size class.

    A single commit is a sample when it fits a class. The class "huge" and any
    class that single commits do not fill use windows of consecutive commits.
    """
    chosen: dict[str, list[Sample]] = {name: [] for name, _, _ in BUCKETS}

    def add(sample: Sample) -> None:
        if len(chosen[sample.bucket]) < per_bucket and not any(
            s.base == sample.base and s.head == sample.head
            for s in chosen[sample.bucket]
        ):
            chosen[sample.bucket].append(sample)

    for sha in commits:
        files, lines = diff_size(repo, f"{sha}^", sha, config)
        bucket = bucket_of(lines)
        if bucket:
            subject = _git(repo, "log", "-1", "--format=%s", sha).strip()
            add(Sample(bucket, f"{sha}^", sha, 1, files, lines, subject[:60]))

    for start in range(len(commits)):
        if all(len(v) >= per_bucket for v in chosen.values()):
            break
        for size in range(2, MAX_WINDOW + 1):
            end = start + size - 1
            if end >= len(commits):
                break
            head, base = commits[start], f"{commits[end]}^"
            files, lines = diff_size(repo, base, head, config)
            bucket = bucket_of(lines)
            if bucket and len(chosen[bucket]) < per_bucket:
                add(Sample(bucket, base, head, size, files, lines, f"{size} commits"))
                break
    return [s for name, _, _ in BUCKETS for s in chosen[name]]


def load_run(path: Path) -> tuple[list[Sample], list[dict]]:
    """Read the samples and the records of an earlier run (its runs.json)."""
    records = json.loads(Path(path).read_text(encoding="utf-8"))["runs"]
    samples: list[Sample] = []
    for r in records:
        sample = Sample(
            r["bucket"],
            r["base"],
            r["head"],
            r["commits"],
            r["files"],
            r["lines"],
            r["label"],
        )
        if sample not in samples:
            samples.append(sample)
    order = [name for name, _, _ in BUCKETS]
    samples.sort(key=lambda s: order.index(s.bucket))
    return samples, records


def render_comparison(old: list[dict], new: list[dict], engine: str = "agent") -> str:
    """Return a Markdown table that compares two runs of one engine for each size class."""
    header = [
        "Class",
        "Time before / after (s)",
        "Steps",
        "Tokens",
        "Budget hit",
        "Critical+warn per run",
    ]
    lines = [
        "## Before and after (same changes)",
        "",
        "Each cell shows the median before and after. Budget hit counts the reviews that ended at a budget.",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for bucket, _, _ in BUCKETS:
        a = summarize(
            [r for r in old if r["bucket"] == bucket and r["engine"] == engine]
        )
        b = summarize(
            [r for r in new if r["bucket"] == bucket and r["engine"] == engine]
        )
        if not a["runs"] and not b["runs"]:
            continue
        lines.append(
            f"| {bucket} | {_fmt(a['median_time'], 1)} / {_fmt(b['median_time'], 1)} | "
            f"{_fmt(a['median_steps'])} / {_fmt(b['median_steps'])} | "
            f"{_fmt(a['median_tokens'])} / {_fmt(b['median_tokens'])} | "
            f"{a['forced']} / {b['forced']} | "
            f"{_fmt(a['findings_per_run'], 1)} / {_fmt(b['findings_per_run'], 1)} |"
        )
    total_a = summarize([r for r in old if r["engine"] == engine])
    total_b = summarize([r for r in new if r["engine"] == engine])
    lines += [
        "",
        f"- Tokens in total: {total_a['total_tokens']} / {total_b['total_tokens']}",
        f"- Median time: {_fmt(total_a['median_time'], 1)} s / {_fmt(total_b['median_time'], 1)} s",
        f"- Reviews that hit a budget: {total_a['forced']} / {total_b['forced']}",
        (
            "- Findings (critical, warnings, suggestions): "
            f"{total_a['critical']}, {total_a['warnings']}, {total_a['suggestions']} / "
            f"{total_b['critical']}, {total_b['warnings']}, {total_b['suggestions']}"
        ),
        "",
    ]
    return "\n".join(lines)


@contextmanager
def working_directory(path: Path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def classic_prompt_tokens(repo: Path, sample: Sample, config_file: Path) -> int:
    """Estimate the tokens of the classic prompt for one sample (one chunk)."""
    with working_directory(repo):
        config = ReviewConfig(str(config_file))
        parser = DiffParser(config)
        files = parser.parse_diff(parser.get_diff("range", sample.base, sample.head))
        reviewer = LLMReviewer(config)
        return reviewer._estimate_tokens(
            reviewer._build_prompt(parser.format_for_llm(files))
        )


def record_of(sample: Sample, engine: str, result: dict, classic_tokens: int) -> dict:
    """Turn the output of one review into a record."""
    record = {
        **asdict(sample),
        "engine": engine,
        "duration_sec": result.get("duration_sec", 0),
        "classic_prompt_tokens": classic_tokens,
    }
    if "error" in result or result.get("status") != "success":
        status = result.get("error") or f"status {result.get('status')}"
        return {**record, "ok": False, "error": status}
    stats = result.get("agent_stats") or {}
    return {
        **record,
        "ok": True,
        "engine_used": result.get("engine"),
        "critical": len(result.get("critical_issues") or []),
        "warnings": len(result.get("warnings") or []),
        "suggestions": len(result.get("suggestions") or [])
        + len(result.get("code_suggestions") or []),
        "redacted": result.get("redacted_count", 0),
        "steps": stats.get("steps"),
        "tokens": stats.get("tokens"),
        "tool_calls": stats.get("tool_calls"),
        "invalid_tool_calls": stats.get("invalid_tool_calls"),
        "forced_submit": stats.get("forced_submit"),
        "fallback": stats.get("fallback"),
        "findings": [
            {"severity": key, "text": str(text)[:300]}
            for key, name in (
                ("critical", "critical_issues"),
                ("warning", "warnings"),
                ("suggestion", "suggestions"),
            )
            for text in result.get(name) or []
        ],
    }


def _med(values: list) -> float | None:
    return percentile([v for v in values if v is not None], 50)


def _p90(values: list) -> float | None:
    return percentile([v for v in values if v is not None], 90)


def _fmt(value, digits=0, unit="") -> str:
    return "-" if value is None else f"{value:.{digits}f}{unit}"


def summarize(records: list[dict]) -> dict:
    good = [r for r in records if r["ok"]]
    agent = [r for r in good if r.get("steps") is not None]
    return {
        "runs": len(records),
        "failed": len(records) - len(good),
        "median_time": _med([r["duration_sec"] for r in good]),
        "p90_time": _p90([r["duration_sec"] for r in good]),
        "median_steps": _med([r["steps"] for r in agent]),
        "median_tokens": _med([r["tokens"] for r in agent]),
        "p90_tokens": _p90([r["tokens"] for r in agent]),
        "total_tokens": sum(r["tokens"] or 0 for r in agent),
        "median_classic_tokens": _med([r["classic_prompt_tokens"] for r in good]),
        "forced": sum(1 for r in agent if r.get("forced_submit")),
        "fallback": sum(1 for r in agent if r.get("fallback")),
        "invalid_calls": sum(r.get("invalid_tool_calls") or 0 for r in agent),
        "tool_calls": sum(r.get("tool_calls") or 0 for r in agent),
        "findings_per_run": (
            sum(r["critical"] + r["warnings"] for r in good) / len(good)
        )
        if good
        else None,
        "critical": sum(r["critical"] for r in good),
        "warnings": sum(r["warnings"] for r in good),
        "suggestions": sum(r["suggestions"] for r in good),
        "redacted": sum(r["redacted"] for r in good),
    }


def render(records: list[dict], meta: dict) -> str:
    """Return the report as Markdown."""
    engines = sorted({r["engine"] for r in records}, key=ENGINES.index)
    samples = []
    for r in records:
        key = (r["bucket"], r["base"], r["head"])
        if key not in [(s["bucket"], s["base"], s["head"]) for s in samples]:
            samples.append(r)
    lines = [
        "# Cost on real changes",
        "",
        f"- Date: {meta.get('date', '-')}",
        f"- Model: {meta.get('model', '-')}",
        f"- Changes: {len(samples)}, engines: {', '.join(engines)}",
        "",
        "## Summary for each size class",
        "",
        (
            "Time is the median and the 90th percentile in seconds. The classic prompt tokens "
            "are an estimate for one chunk. The agent tokens are the sum over all steps."
        ),
        "",
    ]
    header = [
        "Class",
        "Engine",
        "Runs (failed)",
        "Time med / p90",
        "Agent steps",
        "Agent tokens med / p90",
        "Classic prompt tokens",
        "Budget hit",
        "Fallback",
        "Critical+warn per run",
    ]
    lines += [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    for bucket, _, _ in BUCKETS:
        for engine in engines:
            part = [
                r for r in records if r["bucket"] == bucket and r["engine"] == engine
            ]
            if not part:
                continue
            s = summarize(part)
            lines.append(
                f"| {bucket} | {engine} | {s['runs']} ({s['failed']}) | "
                f"{_fmt(s['median_time'], 1)} / {_fmt(s['p90_time'], 1)} | {_fmt(s['median_steps'])} | "
                f"{_fmt(s['median_tokens'])} / {_fmt(s['p90_tokens'])} | {_fmt(s['median_classic_tokens'])} | "
                f"{s['forced']} | {s['fallback']} | {_fmt(s['findings_per_run'], 1)} |"
            )

    lines += ["", "## All changes", ""]
    cols = ["Class", "Change", "Files", "Lines"]
    for engine in engines:
        cols += [f"{engine}: time", f"{engine}: crit/warn/sugg"] + (
            [f"{engine}: steps", f"{engine}: tokens"] if engine == "agent" else []
        )
    lines += ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for sample in samples:
        row = [
            sample["bucket"],
            f"`{sample['head'][:7]}` {sample['label']}",
            str(sample["files"]),
            str(sample["lines"]),
        ]
        for engine in engines:
            r = next(
                (
                    x
                    for x in records
                    if x["engine"] == engine
                    and x["head"] == sample["head"]
                    and x["base"] == sample["base"]
                ),
                None,
            )
            if r is None:
                row += ["-"] * (4 if engine == "agent" else 2)
            elif not r["ok"]:
                row += [f"FAILED: {str(r['error'])[:40]}", "-"] + (
                    ["-", "-"] if engine == "agent" else []
                )
            else:
                note = (
                    " (fallback)"
                    if r.get("fallback")
                    else (" (budget)" if r.get("forced_submit") else "")
                )
                row += [
                    f"{r['duration_sec']:.0f}{note}",
                    f"{r['critical']}/{r['warnings']}/{r['suggestions']}",
                ]
                if engine == "agent":
                    row += [_fmt(r.get("steps")), _fmt(r.get("tokens"))]
        lines.append("| " + " | ".join(row) + " |")

    total = summarize([r for r in records if r["engine"] == "agent"])
    lines += [
        "",
        "## Agent totals",
        "",
        f"- Tokens in total: {total['total_tokens']}",
        f"- Tool calls: {total['tool_calls']}, invalid: {total['invalid_calls']}",
        f"- Reviews that hit a budget: {total['forced']}, that fell back to classic: {total['fallback']}",
        "",
    ]
    return "\n".join(lines)


def write_config(base: Path, destination: Path, log_dir: Path) -> Path:
    """Copy the config and turn the monitoring log on, with the log in log_dir."""
    config = json.loads(base.read_text(encoding="utf-8"))
    config["monitoring"] = {"enabled": True, "log_dir": str(log_dir)}
    destination.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return destination


def main(argv: list[str] | None = None, runner=run_review) -> int:
    parser = argparse.ArgumentParser(
        description="Measure the cost of the engines on real git history"
    )
    parser.add_argument(
        "--repo", default=".", help="Repository to read (default: the current folder)"
    )
    parser.add_argument(
        "--engines",
        default="classic,agent",
        help="Comma-separated: classic, agent, hybrid",
    )
    parser.add_argument(
        "--per-bucket", type=int, default=3, help="Changes for each size class"
    )
    parser.add_argument(
        "--scan", type=int, default=60, help="How many recent commits to scan"
    )
    parser.add_argument("--timeout", type=int, default=900, help="Seconds for one run")
    parser.add_argument(
        "--config", default=str(ROOT / "review_config.json"), help="Base config"
    )
    parser.add_argument(
        "--out", help="Result folder (default: evaluation/results/history-<time>)"
    )
    parser.add_argument(
        "--list", action="store_true", help="List the chosen changes and exit"
    )
    parser.add_argument(
        "--from-run",
        help="runs.json of an earlier run. Use the same changes and compare the result with that run",
    )
    args = parser.parse_args(argv)

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    for engine in engines:
        if engine not in ENGINES:
            parser.error(f"unknown engine '{engine}'")
    if args.per_bucket < 1:
        parser.error("--per-bucket must be 1 or more")
    repo = Path(args.repo).resolve()
    base_config = Path(args.config)
    if not base_config.is_file():
        print(f"Error: config file not found: {base_config}", file=sys.stderr)
        return 4

    config = ReviewConfig(str(base_config))
    baseline: list[dict] = []
    if args.from_run:
        try:
            samples, baseline = load_run(Path(args.from_run))
        except (OSError, ValueError, KeyError) as error:
            print(f"Error: cannot read the earlier run: {error}", file=sys.stderr)
            return 4
    else:
        samples = pick_samples(
            repo, list_commits(repo, args.scan), args.per_bucket, config
        )
    if args.list:
        for s in samples:
            print(
                f"{s.bucket:7} {s.head[:7]}  {s.files:3} files {s.lines:5} lines  {s.label}"
            )
        return 0
    if not samples:
        print("No change of a supported size was found.", file=sys.stderr)
        return 4

    out_dir = (
        Path(args.out)
        if args.out
        else RESULTS_DIR / ("history-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    config_file = write_config(base_config, out_dir / "config.json", out_dir / "logs")

    records: list[dict] = []
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="llm-history-"):
        for sample in samples:
            tokens = classic_prompt_tokens(repo, sample, config_file)
            for engine in engines:
                result = runner(
                    engine,
                    repo,
                    config_file,
                    args.timeout,
                    base=sample.base,
                    head=sample.head,
                )
                record = record_of(sample, engine, result, tokens)
                records.append(record)
                state = "ok" if record["ok"] else f"FAILED ({record['error']})"
                print(
                    f"{sample.bucket:7} {sample.head[:7]} {engine:8} {record['duration_sec']:6.1f} s  {state}",
                    flush=True,
                )

    meta = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "model": (
            json.loads(base_config.read_text(encoding="utf-8")).get("llm") or {}
        ).get("model", "-"),
        "total_seconds": round(time.monotonic() - started),
    }
    report = render(records, meta)
    for engine in engines:
        if baseline and any(r["engine"] == engine for r in baseline):
            report += "\n" + render_comparison(baseline, records, engine)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    (out_dir / "runs.json").write_text(
        json.dumps({"meta": meta, "runs": records}, indent=2), encoding="utf-8"
    )
    print()
    print(report)
    print(f"Saved in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
