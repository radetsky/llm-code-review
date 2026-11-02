#!/usr/bin/env python3
"""
Utilities for monitoring and maintenance of LLM code review system.
"""

import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

# Add current directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config import ReviewConfig
from review_core import LLMReviewer, ReviewResult


class MonitoringUtils:
    """Utilities for monitoring LLM code review system."""

    def __init__(self, config=None, logs_dir=None):
        self.config = config or ReviewConfig()
        self.logs_dir = Path(logs_dir or self.config.get("monitoring.log_dir", "logs"))

    def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        results = {"timestamp": datetime.now().isoformat(), "checks": {}}

        # Check configuration
        config_status = self._check_configuration()
        results["checks"]["configuration"] = config_status

        # Check git repository
        git_status = self._check_git_repository()
        results["checks"]["git"] = git_status

        # Check LLM connection
        llm_status = self._check_llm_connection()
        results["checks"]["llm"] = llm_status

        # Check hooks installation
        hooks_status = self._check_hooks()
        results["checks"]["hooks"] = hooks_status

        # Overall status
        results["overall_status"] = (
            "healthy"
            if all(check.get("status") == "ok" for check in results["checks"].values())
            else "unhealthy"
        )

        return results

    def _check_configuration(self) -> Dict[str, Any]:
        """Check configuration files and environment."""
        result = {"status": "ok", "details": {}}

        # Check config file
        if Path(self.config.config_file).exists():
            result["details"]["config_file"] = "exists"
        else:
            result["details"]["config_file"] = "missing"
            result["status"] = "warning"

        # Check API key
        api_key = self.config.get_api_key()
        if api_key:
            result["details"]["api_key"] = "configured"
        else:
            result["details"]["api_key"] = "missing"
            result["status"] = "error"

        # Check Python dependencies
        try:
            result["details"]["dependencies"] = "ok"
        except ImportError:
            result["details"]["dependencies"] = "missing"
            result["status"] = "error"

        return result

    def _check_git_repository(self) -> Dict[str, Any]:
        """Check git repository status."""
        result = {"status": "ok", "details": {}}

        import subprocess

        try:
            # Check if in git repository
            subprocess.run(
                ["git", "rev-parse", "--git-dir"], check=True, capture_output=True
            )
            result["details"]["repository"] = "ok"

            # Check for staged changes
            staged_result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                capture_output=True,
                text=True,
            )
            staged_files = (
                staged_result.stdout.strip().split("\n")
                if staged_result.stdout.strip()
                else []
            )
            result["details"]["staged_files"] = len(staged_files)

        except subprocess.CalledProcessError:
            result["details"]["repository"] = "not_a_repo"
            result["status"] = "error"
        except FileNotFoundError:
            result["details"]["repository"] = "git_not_found"
            result["status"] = "error"

        return result

    def _check_llm_connection(self) -> Dict[str, Any]:
        """Check LLM connection."""
        result = {"status": "ok", "details": {}}

        try:
            reviewer = LLMReviewer(self.config)
            if reviewer.test_connection():
                result["details"]["connection"] = "ok"
                result["details"]["model"] = self.config.get_model()
            else:
                result["details"]["connection"] = "failed"
                result["status"] = "error"
        except Exception as e:
            result["details"]["connection"] = f"error: {str(e)}"
            result["status"] = "error"

        return result

    def _check_hooks(self) -> Dict[str, Any]:
        """Check git hooks installation."""
        result = {"status": "ok", "details": {}}

        hooks_dir = Path(".git/hooks")
        required_hooks = ["pre-commit", "pre-push"]

        for hook in required_hooks:
            hook_file = hooks_dir / hook
            if hook_file.exists() and os.access(hook_file, os.X_OK):
                result["details"][hook] = "installed"
            else:
                result["details"][hook] = "missing"
                result["status"] = "warning"

        return result

    def log_review_result(
        self, result: ReviewResult, metadata: Optional[Dict[str, Any]] = None
    ):
        """Write one line to the log of the day.

        The metadata can hold: engine, duration_sec, model, mode and files.
        The method creates the log folder when it writes the first line.
        """
        stats = result.agent_stats or {}
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "result": {
                "status": result.status,
                "review_outcome": result.review_outcome,
                "critical_count": len(result.critical_issues),
                "warning_count": len(result.warnings),
                "suggestion_count": len(result.suggestions)
                + len(result.code_suggestions),
                "fallback_used": result.fallback_used,
            },
            "metadata": metadata if metadata is not None else {},
        }
        if stats:
            log_entry["agent"] = {
                key: stats.get(key) for key in AGENT_STAT_KEYS if key in stats
            }

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.logs_dir / f"reviews_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

    def read_entries(self, days: int) -> list:
        """Return the log entries of the last days, oldest first."""
        entries = []
        for i in reversed(range(days)):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            log_file = self.logs_dir / f"reviews_{date}.jsonl"
            if not log_file.exists():
                continue
            with open(log_file, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and isinstance(
                        entry.get("result"), dict
                    ):
                        entries.append(entry)
        return entries

    def generate_report(self, days: int = 7) -> Dict[str, Any]:
        """Generate monitoring report for specified period."""
        entries = self.read_entries(days)
        report = {
            "period_days": days,
            "generated_at": datetime.now().isoformat(),
            "summary": summarize(entries),
            "by_engine": {},
            "details": entries[-10:],  # Last 10 reviews
        }
        for engine in sorted({engine_of(e) for e in entries}):
            report["by_engine"][engine] = summarize(
                [e for e in entries if engine_of(e) == engine]
            )
        return report


# Keys of the agent statistics that the log keeps.
AGENT_STAT_KEYS = (
    "steps",
    "step_target",
    "tokens",
    "tool_calls",
    "invalid_tool_calls",
    "duplicate_tool_calls",
    "ignored_tool_calls",
    "forced_submit",
    "stop_reason",
    "dropped_findings",
    "duration_sec",
    "fallback",
    "fallback_reason",
)


def engine_of(entry: dict) -> str:
    return str((entry.get("metadata") or {}).get("engine") or "unknown")


def percentile(values: list, percent: float):
    """Return the value at the percentile (nearest rank), or None."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * percent // 100))  # Round up.
    return ordered[int(rank) - 1]


def _ratio(numerator: float, denominator: float):
    return numerator / denominator if denominator else None


def summarize(entries: list) -> dict:
    """Summarize log entries. Old entries without the newer fields are accepted."""
    total = len(entries)
    results = [e["result"] for e in entries]
    successful = sum(1 for r in results if r.get("status") == "success")
    durations = [
        e["metadata"]["duration_sec"]
        for e in entries
        if isinstance(e.get("metadata"), dict)
        and isinstance(e["metadata"].get("duration_sec"), (int, float))
    ]
    agent = [e["agent"] for e in entries if isinstance(e.get("agent"), dict)]
    agent = [a for a in agent if isinstance(a.get("steps"), (int, float))]
    tokens = [a["tokens"] for a in agent if isinstance(a.get("tokens"), (int, float))]
    calls = sum(a.get("tool_calls") or 0 for a in agent)
    invalid = sum(a.get("invalid_tool_calls") or 0 for a in agent)
    critical = sum(r.get("critical_count", 0) for r in results)
    warnings = sum(r.get("warning_count", 0) for r in results)

    return {
        "total_reviews": total,
        "successful_reviews": successful,
        "unavailable_reviews": sum(
            1 for r in results if r.get("status") == "model_unavailable"
        ),
        "success_rate": _ratio(successful * 100, total) or 0,
        "total_critical_issues": critical,
        "total_warnings": warnings,
        "avg_critical_per_review": _ratio(critical, total) or 0,
        "avg_warnings_per_review": _ratio(warnings, total) or 0,
        "median_duration_sec": percentile(durations, 50),
        "p90_duration_sec": percentile(durations, 90),
        "agent_reviews": len(agent),
        "median_steps": percentile([a["steps"] for a in agent], 50),
        "p90_steps": percentile([a["steps"] for a in agent], 90),
        "median_tokens": percentile(tokens, 50),
        "p90_tokens": percentile(tokens, 90),
        "total_tokens": sum(tokens),
        "invalid_call_rate": _ratio(invalid, calls + invalid),
        "forced_submit_rate": _ratio(
            sum(1 for a in agent if a.get("forced_submit")), len(agent)
        ),
        "fallback_rate": _ratio(sum(1 for a in agent if a.get("fallback")), len(agent)),
    }


def _fmt(value, unit: str = "", digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}{unit}" if digits else f"{value:.0f}{unit}"


def _pct(value) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def format_summary(summary: dict, indent: str = "") -> list:
    """Return the lines of the text report for one summary."""
    duration = (
        f"{_fmt(summary['median_duration_sec'], ' s')} / "
        f"{_fmt(summary['p90_duration_sec'], ' s')}"
    )
    lines = [
        f"Total Reviews: {summary['total_reviews']}",
        f"Success Rate: {summary['success_rate']:.1f}%",
        f"Model Unavailable: {summary['unavailable_reviews']}",
        f"Total Critical Issues: {summary['total_critical_issues']}",
        f"Total Warnings: {summary['total_warnings']}",
        f"Avg Critical/Review: {summary['avg_critical_per_review']:.1f}",
        f"Avg Warnings/Review: {summary['avg_warnings_per_review']:.1f}",
        f"Time (median / p90): {duration}",
    ]
    if summary["agent_reviews"]:
        steps = f"{_fmt(summary['median_steps'], '', 0)} / {_fmt(summary['p90_steps'], '', 0)}"
        tokens = f"{_fmt(summary['median_tokens'], '', 0)} / {_fmt(summary['p90_tokens'], '', 0)}"
        lines += [
            f"Agent reviews: {summary['agent_reviews']}",
            f"Steps (median / p90): {steps}",
            f"Tokens (median / p90): {tokens}",
            f"Tokens in total: {summary['total_tokens']}",
            f"Invalid tool calls: {_pct(summary['invalid_call_rate'])}",
            f"Reviews that hit a budget: {_pct(summary['forced_submit_rate'])}",
            f"Reviews that fell back to classic: {_pct(summary['fallback_rate'])}",
        ]
    return [indent + line for line in lines]


def main():
    """CLI interface for monitoring utilities."""
    import argparse

    parser = argparse.ArgumentParser(description="LLM Code Review Monitoring Utilities")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Health check command
    subparsers.add_parser("health", help="Perform health check")

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate monitoring report")
    report_parser.add_argument(
        "--days", type=int, default=7, help="Number of days to include in report"
    )
    report_parser.add_argument(
        "--json", action="store_true", help="Print the report as JSON"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    monitor = MonitoringUtils()

    if args.command == "health":
        print("🏥 LLM Code Review Health Check")
        print("=" * 40)

        health = monitor.health_check()

        print(f"Overall Status: {health['overall_status'].upper()}")
        print("")

        for check_name, check_result in health["checks"].items():
            if check_result["status"] == "ok":
                status_icon = "✅"
            elif check_result["status"] == "warning":
                status_icon = "⚠️"
            else:
                status_icon = "❌"

            print(f"{status_icon} {check_name.title()}: {check_result['status']}")

            for detail_name, detail_value in check_result["details"].items():
                print(f"   • {detail_name}: {detail_value}")
            print("")

    elif args.command == "report":
        report = monitor.generate_report(args.days)

        if args.json:
            print(json.dumps(report, indent=2))
            return

        print(f"📊 LLM Code Review Report (Last {args.days} days)")
        print("=" * 50)

        if report["summary"]["total_reviews"] == 0:
            print("No reviews in this period.")
            print(
                "Turn on the log with monitoring.enabled in the config "
                "or with the environment variable LLM_MONITORING=1."
            )
            return

        print("\n".join(format_summary(report["summary"])))
        for engine, summary in report["by_engine"].items():
            print(f"\nEngine: {engine}")
            print("\n".join(format_summary(summary, "  ")))


if __name__ == "__main__":
    main()
