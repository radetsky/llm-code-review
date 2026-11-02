"""Markdown report for the evaluation results."""

from evaluation.scoring import aggregate, per_case


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def _num(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}" if digits else f"{value:.0f}"


def _tokens(value: float | None) -> str:
    return "-" if value is None else f"{value / 1000:.0f}k"


SUMMARY_ROWS = [
    ("Runs (failed)", lambda a: f"{a['runs']} ({a['failed_runs']})"),
    ("Runs that fell back to classic", lambda a: str(a["fallback_runs"])),
    (
        "Recall (problems found)",
        lambda a: f"{a['found']}/{a['expected']} = {_pct(a['recall'])}",
    ),
    ("Recall with the right severity", lambda a: _pct(a["recall_severity_ok"])),
    ("Precision (critical and warning)", lambda a: _pct(a["precision"])),
    ("False positives in total", lambda a: str(a["false_positives"])),
    ("False positives per run", lambda a: _num(a["false_positives_per_run"], 2)),
    (
        "Clean runs with a false positive",
        lambda a: _pct(a["clean_runs_with_false_positive"]),
    ),
    ("Extra suggestions per run", lambda a: _num(a["extra_suggestions_per_run"], 2)),
    ("Findings without file and line", lambda a: str(a["unanchored"])),
    ("Median time (s)", lambda a: _num(a["median_duration_sec"])),
    ("Median steps", lambda a: _num(a["median_steps"], 0)),
    ("Median tokens", lambda a: _tokens(a["median_tokens"])),
    ("Invalid tool calls", lambda a: _pct(a["invalid_call_rate"])),
    ("Reviews that hit a budget", lambda a: _pct(a["forced_submit_rate"])),
]


def render(runs_by_engine: dict[str, list[dict]], meta: dict) -> str:
    """Return the report as Markdown."""
    engines = list(runs_by_engine)
    summaries = {e: aggregate(runs_by_engine[e]) for e in engines}
    lines = [
        "# Evaluation report",
        "",
        f"- Date: {meta.get('date', '-')}",
        f"- Model: {meta.get('model', '-')}",
        f"- Cases: {meta.get('cases', '-')}, runs for each case: {meta.get('runs', '-')}",
        f"- Line tolerance: {meta.get('tolerance', '-')}",
        "",
        "## Summary",
        "",
        "| Metric | " + " | ".join(engines) + " |",
        "|---|" + "|".join("---:" for _ in engines) + "|",
    ]
    for label, getter in SUMMARY_ROWS:
        lines.append(
            f"| {label} | " + " | ".join(getter(summaries[e]) for e in engines) + " |"
        )

    lines += ["", "## Cases", ""]
    cases = sorted({r["case"] for runs in runs_by_engine.values() for r in runs})
    header = ["Case"]
    for e in engines:
        header += [f"{e}: found", f"{e}: false pos.", f"{e}: steps", f"{e}: time (s)"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|---|" + "|".join("---:" for _ in header[1:]) + "|")
    details = {e: per_case(runs_by_engine[e]) for e in engines}
    for case in cases:
        row = [case]
        for e in engines:
            d = details[e].get(case)
            if not d:
                row += ["-"] * 4
                continue
            found = ",".join(str(n) for n in d["found_runs"]) or "-"
            expected = "-" if d["expected"] is None else d["expected"]
            fps = ",".join(str(n) for n in d["false_positives"]) or "-"
            row += [
                f"{found} of {expected}",
                fps,
                _num(d["median_steps"], 0),
                _num(d["median_duration_sec"], 0),
            ]
        lines.append("| " + " | ".join(row) + " |")
    lines += [
        "",
        "Found and false positives list one number for each run. Steps and time are medians.",
    ]

    failures = [(e, r) for e in engines for r in runs_by_engine[e] if not r["ok"]]
    if failures:
        lines += ["", "## Failed runs", ""]
        for engine, run in failures:
            lines.append(
                f"- {engine} / {run['case']}: {run.get('error', 'unknown error')}"
            )
    return "\n".join(lines) + "\n"
