"""
Read the result file of a review run and print the outputs of the action.

The action calls this script after review.py. The script prints lines in the
format key=value. The action appends these lines to GITHUB_OUTPUT. The script
never fails: if the result is not valid, it reports status=error.

Usage: read_result.py RESULT_FILE STDERR_FILE EXIT_CODE
"""

import json
import sys
from pathlib import Path

# The error line comes from the output of a program. Hide secrets in it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from redaction import redact
except ImportError:  # The script still works if the module is not there.

    def redact(text, generic=True):
        return text, 0


MAX_MESSAGE = 300


def one_line(text: str) -> str:
    """Return the text on one line and at most MAX_MESSAGE characters."""
    flat = redact(" ".join(str(text).split()))[0]
    return flat[:MAX_MESSAGE]


def last_line(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = [line.strip() for line in handle if line.strip()]
    except OSError:
        return ""
    return lines[-1] if lines else ""


def summarize(result_path: str, stderr_path: str, exit_code: str) -> dict:
    """Return the outputs of the action as a dict."""
    try:
        with open(result_path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise TypeError("The result is not a JSON object")
    except (OSError, ValueError, TypeError):
        reason = last_line(stderr_path) or f"review.py exited with code {exit_code}"
        return {
            "status": "error",
            "outcome": "none",
            "critical_count": 0,
            "warning_count": 0,
            "suggestion_count": 0,
            "engine": "unknown",
            "error": one_line(reason),
        }

    status = str(data.get("status", "unknown"))
    outcome = str(data.get("review_outcome", "none")) if status == "success" else "none"
    code_suggestions = data.get("code_suggestions") or []
    return {
        "status": status,
        "outcome": outcome,
        "critical_count": len(data.get("critical_issues") or []),
        "warning_count": len(data.get("warnings") or []),
        "suggestion_count": len(data.get("suggestions") or []) + len(code_suggestions),
        "engine": one_line(data.get("engine") or "unknown"),
        "error": "",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(
            "Usage: read_result.py RESULT_FILE STDERR_FILE EXIT_CODE", file=sys.stderr
        )
        return 2
    for key, value in summarize(argv[1], argv[2], argv[3]).items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
