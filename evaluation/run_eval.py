"""
Run the review engines on the golden cases and write a report.

Example:
    python -m evaluation.run_eval --engines classic,agent --runs 3

Each run starts review.py in a new git repository that holds one case. The
script needs the LLM settings in the environment (LLM_API_KEY, LLM_BASE_URL).
It never prints them.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from config import ENGINES
from evaluation.cases import BASE_BRANCH, HEAD_BRANCH, build_repo, load_cases
from evaluation.report import render
from evaluation.scoring import parse_findings, score_run

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = Path(__file__).parent / "results"


def write_case_config(
    base_config: Path, extra_extensions: list[str], destination: Path
) -> Path:
    """Write the config for one case: the base config plus extra file extensions."""
    config = json.loads(base_config.read_text(encoding="utf-8"))
    review = config.setdefault("review", {})
    extensions = list(review.get("file_extensions", []))
    for extension in extra_extensions:
        if extension not in extensions:
            extensions.append(extension)
    review["file_extensions"] = extensions
    destination.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return destination


def run_review(
    engine: str,
    repo: Path,
    config_file: Path,
    timeout: int,
    base: str = BASE_BRANCH,
    head: str = HEAD_BRANCH,
) -> dict:
    """Run review.py in the repository. Return the JSON result and the timing.

    The result has the key "error" when the run failed.
    """
    command = [
        sys.executable,
        str(ROOT / "review.py"),
        "--engine",
        engine,
        "--base",
        base,
        "--head",
        head,
        "--format",
        "json",
        "--config-file",
        str(config_file),
    ]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout} s", "duration_sec": timeout}
    duration = round(time.monotonic() - started, 2)
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
        return {
            "error": f"exit {proc.returncode}: {tail[0][:200]}",
            "duration_sec": duration,
        }
    data["duration_sec"] = duration
    return data


def evaluate_run(case, result: dict, tolerance: int) -> dict:
    """Turn the output of one review into a run record."""
    record = {
        "case": case.id,
        "clean": case.is_clean,
        "duration_sec": result.get("duration_sec", 0),
        "engine_used": result.get("engine"),
        "stats": result.get("agent_stats"),
    }
    if "error" in result:
        return {**record, "ok": False, "error": result["error"], "score": None}
    if result.get("status") != "success":
        # The model did not answer. The result holds the static fallback only.
        return {
            **record,
            "ok": False,
            "error": f"status {result.get('status')}",
            "score": None,
        }
    findings = parse_findings(result)
    record.update(
        ok=True, score=score_run(case.expected, findings, tolerance, case.canaries)
    )
    record["findings"] = [
        {"severity": f.severity, "file": f.file, "line": f.line, "text": f.text[:300]}
        for f in findings
    ]
    return record


def main(argv: list[str] | None = None, runner=run_review) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the review engines on golden cases"
    )
    parser.add_argument(
        "--engines",
        default="classic,agent",
        help="Comma-separated: classic, agent, hybrid",
    )
    parser.add_argument(
        "--runs", type=int, default=1, help="Runs for each case and engine"
    )
    parser.add_argument("--cases", help="Comma-separated case names (default: all)")
    parser.add_argument(
        "--tolerance", type=int, default=2, help="Allowed line distance"
    )
    parser.add_argument("--timeout", type=int, default=600, help="Seconds for one run")
    parser.add_argument(
        "--config", default=str(ROOT / "review_config.json"), help="Base config"
    )
    parser.add_argument(
        "--out", help="Result folder (default: evaluation/results/<time>)"
    )
    parser.add_argument("--list", action="store_true", help="List the cases and exit")
    args = parser.parse_args(argv)

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    for engine in engines:
        if engine not in ENGINES:
            parser.error(f"unknown engine '{engine}'")
    if args.runs < 1:
        parser.error("--runs must be 1 or more")
    try:
        cases = load_cases(
            [c.strip() for c in args.cases.split(",")] if args.cases else None
        )
    except ValueError as error:
        parser.error(str(error))

    if args.list:
        for case in cases:
            kind = "clean" if case.is_clean else f"{len(case.expected)} expected"
            print(f"{case.id:24} {kind:12} {case.description}")
        return 0

    base_config = Path(args.config)
    if not base_config.is_file():
        print(f"Error: config file not found: {base_config}", file=sys.stderr)
        return 4
    out_dir = (
        Path(args.out)
        if args.out
        else RESULTS_DIR / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    runs_by_engine: dict[str, list[dict]] = {engine: [] for engine in engines}
    with tempfile.TemporaryDirectory(prefix="llm-eval-") as work:
        for case in cases:
            repo = build_repo(case, Path(work) / case.id)
            config_file = write_case_config(
                base_config, case.extra_extensions, Path(work) / f"{case.id}.json"
            )
            for engine in engines:
                for number in range(1, args.runs + 1):
                    result = runner(engine, repo, config_file, args.timeout)
                    record = evaluate_run(case, result, args.tolerance)
                    record["run"] = number
                    runs_by_engine[engine].append(record)
                    state = "ok" if record["ok"] else f"FAILED ({record['error']})"
                    print(
                        f"{case.id:24} {engine:8} run {number}/{args.runs}  "
                        f"{record['duration_sec']:6.1f} s  {state}",
                        flush=True,
                    )

    base = json.loads(base_config.read_text(encoding="utf-8"))
    meta = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "model": (base.get("llm") or {}).get("model", "-"),
        "cases": len(cases),
        "runs": args.runs,
        "tolerance": args.tolerance,
    }
    report = render(runs_by_engine, meta)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    (out_dir / "runs.json").write_text(
        json.dumps({"meta": meta, "runs": runs_by_engine}, indent=2), encoding="utf-8"
    )
    print()
    print(report)
    print(f"Saved in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
