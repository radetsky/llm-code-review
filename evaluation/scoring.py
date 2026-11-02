"""
Scoring of review results against the expected problems.

This module has no network access. It works on the JSON that review.py
prints with --format json.
"""

import re
import statistics
from dataclasses import dataclass

SEVERITY_RANK = {"critical": 0, "warning": 1, "suggestion": 2}
# Matches "path/to/file.py:42: text" and "path/to/file.py:42-45: text".
FINDING_RE = re.compile(
    r"^\W*?`?([\w./\\-]+\.\w+)`?:(\d+)(?:-(\d+))?:\s*(.*)$", re.DOTALL
)


@dataclass
class Finding:
    severity: str
    file: str | None
    line: int | None
    line_end: int | None
    text: str

    @property
    def anchored(self) -> bool:
        return self.file is not None and self.line is not None


def parse_findings(result: dict) -> list[Finding]:
    """Return all findings of one review result."""
    findings: list[Finding] = []
    for key, severity in (
        ("critical_issues", "critical"),
        ("warnings", "warning"),
        ("suggestions", "suggestion"),
    ):
        for text in result.get(key) or []:
            match = FINDING_RE.match(text) if isinstance(text, str) else None
            if match:
                line = int(match.group(2))
                end = int(match.group(3)) if match.group(3) else line
                findings.append(
                    Finding(
                        severity,
                        match.group(1).removeprefix("./"),
                        line,
                        end,
                        match.group(4),
                    )
                )
            else:
                findings.append(Finding(severity, None, None, None, str(text)))
    for item in result.get("code_suggestions") or []:
        findings.append(
            Finding(
                "suggestion",
                str(item.get("file", "")).removeprefix("./") or None,
                item.get("line_start"),
                item.get("line_end") or item.get("line_start"),
                str(item.get("description", "")),
            )
        )
    return findings


def _matches(finding: Finding, expected, tolerance: int) -> bool:
    return (
        finding.anchored
        and finding.file == expected.file
        and finding.line_end >= expected.line - tolerance
        and finding.line <= expected.line + tolerance
    )


def score_run(expected: list, findings: list[Finding], tolerance: int = 2) -> dict:
    """Compare the findings of one run with the expected problems.

    Only critical issues and warnings count for precision. Suggestions that
    match no expected problem are counted as extra suggestions.
    """
    found = found_severity_ok = 0
    for item in expected:
        hits = [f for f in findings if _matches(f, item, tolerance)]
        if hits:
            found += 1
            if any(SEVERITY_RANK[f.severity] <= SEVERITY_RANK[item.kind] for f in hits):
                found_severity_ok += 1

    main = [f for f in findings if f.severity in ("critical", "warning")]
    true_positive = [
        f for f in main if any(_matches(f, e, tolerance) for e in expected)
    ]
    extra_suggestions = [
        f
        for f in findings
        if f.severity == "suggestion"
        and not any(_matches(f, e, tolerance) for e in expected)
    ]
    return {
        "expected": len(expected),
        "found": found,
        "found_severity_ok": found_severity_ok,
        "findings": len(main),
        "true_positive_findings": len(true_positive),
        "false_positives": len(main) - len(true_positive),
        "extra_suggestions": len(extra_suggestions),
        "unanchored": sum(1 for f in findings if not f.anchored),
    }


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def aggregate(runs: list[dict]) -> dict:
    """Summarize the runs of one engine.

    A run is a dict with these keys: case, clean, ok, score, stats, duration_sec,
    engine_used. Runs with ok=False count as failures and do not enter the
    quality figures.
    """
    good = [r for r in runs if r["ok"]]
    scores = [r["score"] for r in good]
    total = lambda key: sum(s[key] for s in scores)
    clean = [r for r in good if r["clean"]]
    agent_runs = [r["stats"] for r in good if r.get("stats") and "steps" in r["stats"]]
    calls = sum(s.get("tool_calls", 0) for s in agent_runs)
    invalid = sum(s.get("invalid_tool_calls", 0) for s in agent_runs)

    return {
        "runs": len(runs),
        "failed_runs": len(runs) - len(good),
        "fallback_runs": sum(1 for r in good if "->" in (r.get("engine_used") or "")),
        "expected": total("expected"),
        "found": total("found"),
        "recall": _ratio(total("found"), total("expected")),
        "recall_severity_ok": _ratio(total("found_severity_ok"), total("expected")),
        "findings": total("findings"),
        "precision": _ratio(total("true_positive_findings"), total("findings")),
        "false_positives": total("false_positives"),
        "false_positives_per_run": _ratio(total("false_positives"), len(good)),
        "clean_runs_with_false_positive": _ratio(
            sum(1 for r in clean if r["score"]["false_positives"] > 0), len(clean)
        ),
        "extra_suggestions_per_run": _ratio(total("extra_suggestions"), len(good)),
        "unanchored": total("unanchored"),
        "median_duration_sec": _median([r["duration_sec"] for r in good]),
        "median_steps": _median([s["steps"] for s in agent_runs]),
        "median_tokens": _median([s["tokens"] for s in agent_runs]),
        "invalid_call_rate": _ratio(invalid, calls + invalid),
        "forced_submit_rate": _ratio(
            sum(1 for s in agent_runs if s.get("forced_submit")), len(agent_runs)
        ),
    }


def per_case(runs: list[dict]) -> dict[str, dict]:
    """Summarize the runs of one engine for each case."""
    result: dict[str, dict] = {}
    for case in sorted({r["case"] for r in runs}):
        case_runs = [r for r in runs if r["case"] == case]
        good = [r for r in case_runs if r["ok"]]
        steps = [
            r["stats"]["steps"]
            for r in good
            if r.get("stats") and "steps" in r["stats"]
        ]
        result[case] = {
            "runs": len(case_runs),
            "failed_runs": len(case_runs) - len(good),
            "expected": good[0]["score"]["expected"] if good else None,
            "found_runs": [r["score"]["found"] for r in good],
            "false_positives": [r["score"]["false_positives"] for r in good],
            "median_duration_sec": _median([r["duration_sec"] for r in good]),
            "median_steps": _median(steps),
        }
    return result
