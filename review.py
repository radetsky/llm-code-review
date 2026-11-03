#!/usr/bin/env python3
"""
CLI interface for LLM code review system.
Supports multiple review modes and output formats.
"""

import argparse
import json
import logging
import sys
import time
from typing import Dict, Any
from pathlib import Path
from config import ReviewConfig
from agent_core import AgentReviewer
from agent_tools import AgentTools
from diff_parser import DiffParser, RepoSource
from redaction import redact, redact_result
from review_core import LLMReviewer, ReviewResult


def setup_logging(verbose: bool = False):
    """Configure logging based on verbosity level."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


# Add current directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent))


class ReviewCLI:
    """Command-line interface for code review."""

    def __init__(self, trace: bool = False, trace_llm: bool = False):
        self.config = ReviewConfig()
        self.parser = DiffParser(self.config)
        self.reviewer = LLMReviewer(self.config, trace=trace, trace_llm=trace_llm)
        self.trace = trace
        self.trace_llm = trace_llm
        self.engine_used = "classic"

    def run(self, args=None):
        """Run CLI with provided arguments."""
        parser = self._create_parser()
        parsed_args = parser.parse_args(args)

        # Setup logging based on verbosity
        setup_logging(getattr(parsed_args, "verbose", False))

        # Load the config file that the user names
        if getattr(parsed_args, "config_file", None):
            self.config = ReviewConfig(parsed_args.config_file)
            self.parser = DiffParser(self.config)
            self.reviewer = LLMReviewer(
                self.config, trace=self.trace, trace_llm=self.trace_llm
            )

        # Update trace mode if specified
        self.trace = getattr(parsed_args, "trace", False)
        self.trace_llm = getattr(parsed_args, "trace_llm", False)
        self.reviewer.trace = self.trace
        self.reviewer.trace_llm = self.trace_llm

        # Apply the agent budgets from the command line
        for value, key, name in (
            (getattr(parsed_args, "max_steps", None), "max_steps", "--max-steps"),
            (
                getattr(parsed_args, "wall_timeout", None),
                "wall_timeout_sec",
                "--wall-timeout",
            ),
        ):
            if value is None:
                continue
            if value < 1:
                print(f"Error: {name} must be 1 or more.", file=sys.stderr)
                return 2
            self.config.config.setdefault("agent", {})[key] = value

        # Resolve engine and failure policy
        try:
            engine = self.config.get_engine(getattr(parsed_args, "engine", None))
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 4
        explicit = getattr(parsed_args, "fail_on", None)
        if parsed_args.strict and explicit not in (None, "warnings"):
            print(
                f"Error: --strict is an alias of --fail-on warnings and conflicts "
                f"with --fail-on {explicit}.",
                file=sys.stderr,
            )
            return 2
        parsed_args.fail_on = "warnings" if parsed_args.strict else (explicit or "none")

        # Handle mutually exclusive --offline and --test-connection
        run_checks = parsed_args.test_connection or parsed_args.test_tools
        if parsed_args.offline and run_checks:
            print(
                "Error: --offline cannot be combined with --test-connection or --test-tools.",
                file=sys.stderr,
            )
            return 4

        # Handle LLM checks before validation
        if run_checks:
            if not self._validate_config():
                return 4  # Configuration error

            checks = []
            if parsed_args.test_connection:
                checks.append(("Connection to LLM", self.reviewer.test_connection))
            if parsed_args.test_tools:
                checks.append(("Tool calling", self.reviewer.test_tools))

            failed = False
            for label, check in checks:
                ok = check()
                print(
                    f"{'✅' if ok else '❌'} {label} {'successful' if ok else 'failed'}"
                )
                failed = failed or not ok
            return 1 if failed else 0

        # Validate configuration
        if parsed_args.offline:
            try:
                self.parser._run_git(["rev-parse", "--git-dir"])
            except RuntimeError:
                print("Error: Not in a git repository.", file=sys.stderr)
                return 4
        elif not self._validate_config():
            return 4  # Configuration error

        # Validate argument combinations
        if (parsed_args.base and not parsed_args.head) or (
            parsed_args.head and not parsed_args.base
        ):
            print(
                "Error: --base and --head must be provided together for range diff.",
                file=sys.stderr,
            )
            return 2
        if parsed_args.mode and (parsed_args.base or parsed_args.head):
            print(
                "Error: --mode cannot be used together with --base/--head.",
                file=sys.stderr,
            )
            return 2

        try:
            # Perform review
            started = time.monotonic()
            if parsed_args.offline:
                self.engine_used = "static"
                result = self._run_offline_review(parsed_args)
            else:
                parsed_files, diff_content = self._load_diff(parsed_args)
                if engine == "agent":
                    result = self._run_agent_review(
                        parsed_args, parsed_files, diff_content
                    )
                else:
                    self.engine_used = "classic"
                    result = self.reviewer.review_diff(diff_content)

            # The text of the review can reach a public place. Hide secrets first.
            redact_result(result)
            self._log_monitoring(result, parsed_args, time.monotonic() - started)

            # Output results
            self._output_results(result, parsed_args)

            # Return appropriate exit code
            return self._get_exit_code(result, parsed_args)

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 4  # Configuration/execution error

    def _create_parser(self) -> argparse.ArgumentParser:
        """Create command-line argument parser."""
        parser = argparse.ArgumentParser(
            description="LLM-powered code review tool",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  python review.py --mode staged                     # Review staged changes
  python review.py --mode unstaged --format json     # Review unstaged in JSON
  python review.py --mode all --fail-on warnings     # Exit 1 on warnings too
  python review.py --mode staged --engine agent      # Agentic review with tools
  python review.py --base main --head feature        # Review between branches
  python review.py --mode staged --offline           # Offline static analysis only
            """,
        )

        # Review mode selection
        parser.add_argument(
            "--mode",
            choices=["staged", "unstaged", "all"],
            help="Review mode: staged changes, unstaged changes, or all changes from HEAD",
        )

        # Range diff options (can be used together)
        parser.add_argument(
            "--base", help="Base commit/branch for range diff (requires --head)"
        )
        parser.add_argument(
            "--head", help="Head commit/branch for range diff (requires --base)"
        )

        # Output options
        parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="Output format (default: text)",
        )
        parser.add_argument(
            "--engine",
            choices=["agent", "classic"],
            help="Review engine (default: LLM_ENGINE, then agent.enabled, then classic)",
        )
        parser.add_argument(
            "--fail-on",
            dest="fail_on",
            choices=["none", "critical", "warnings"],
            help="Exit 1 on critical issues / any issues. Default: none "
            "(the review is advisory and exits 0)",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Alias for --fail-on warnings",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Verbose output with additional context",
        )
        parser.add_argument(
            "--trace",
            action="store_true",
            help="Trace output: LLM queries, agent steps and tool calls",
        )
        parser.add_argument(
            "--trace-llm",
            action="store_true",
            help="Dump full LLM requests and responses (incl. tool calls) to stderr",
        )
        parser.add_argument(
            "--offline",
            action="store_true",
            help="Run static analysis only, without LLM (forces docstring checks)",
        )

        parser.add_argument(
            "--max-steps",
            type=int,
            metavar="N",
            help="Agent engine: maximum number of exploration steps (config agent.max_steps)",
        )
        parser.add_argument(
            "--wall-timeout",
            type=int,
            metavar="SECONDS",
            help="Agent engine: time limit for one review (config agent.wall_timeout_sec)",
        )

        # Context lines for diff
        parser.add_argument(
            "--context",
            type=int,
            metavar="N",
            help="Number of context lines around each change (default: 10)",
        )

        # Utility commands
        parser.add_argument(
            "--test-connection", action="store_true", help="Test connection to LLM API"
        )
        parser.add_argument(
            "--test-tools",
            action="store_true",
            help="Test that the LLM supports tool calling",
        )
        parser.add_argument(
            "--config-file",
            help="Path to configuration file (default: review_config.json)",
        )

        return parser

    def _validate_config(self) -> bool:
        """Validate configuration."""
        # Check API key
        if not self.config.get_api_key():
            print(
                "Error: API key not found. Set LLM_API_KEY environment variable.",
                file=sys.stderr,
            )
            return False

        # Check base URL
        if not self.config.get_base_url():
            print(
                "Error: Base URL not found. Set LLM_BASE_URL environment variable.",
                file=sys.stderr,
            )
            return False

        # Check if in git repository
        try:
            self.parser._run_git(["rev-parse", "--git-dir"])
        except RuntimeError:
            print("Error: Not in a git repository.", file=sys.stderr)
            return False

        return True

    def _log_monitoring(self, result: ReviewResult, args, duration: float) -> None:
        """Write the review to the monitoring log, if the log is on.

        A failure here never changes the result of the review.
        """
        if not self.config.get_monitoring_enabled():
            return
        try:
            from monitor import MonitoringUtils

            mode = args.mode or ("range" if args.base else "staged")
            MonitoringUtils(self.config).log_review_result(
                result,
                {
                    "engine": self.engine_used,
                    "duration_sec": round(duration, 2),
                    "mode": mode,
                    "model": self.config.get_model(),
                },
            )
        except Exception as error:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "Could not write the review log: %s", error
            )

    def _load_diff(self, args) -> tuple[list, str]:
        """Return (parsed_files, formatted_diff) for the requested diff."""
        if getattr(args, "context", None) is not None:
            self.config.config["output"]["max_context_lines"] = args.context

        if args.base and args.head:
            diff_text = self.parser.get_diff("range", args.base, args.head)
        elif args.mode:
            diff_text = self.parser.get_diff(args.mode)
        else:
            diff_text = self.parser.get_diff("staged")

        # Parse and format for LLM
        parsed_files = self.parser.parse_diff(diff_text)
        formatted_diff = self.parser.format_for_llm(parsed_files)

        if args.verbose and formatted_diff:
            print(f"Analyzing {len(parsed_files)} file(s):", file=sys.stderr)
            for file_data in parsed_files:
                print(f"  - {file_data['path']} ({file_data['type']})", file=sys.stderr)
            print("", file=sys.stderr)

        return parsed_files, formatted_diff

    def _get_diff_content(self, args) -> str:
        """Get formatted diff content based on arguments."""
        return self._load_diff(args)[1]

    def _run_agent_review(self, args, parsed_files, diff_content) -> ReviewResult:
        """Run the agent engine; degrade to the classic engine on failure.

        Chain: agent -> classic (same model) -> static analysis. The classic
        engine already falls back to static analysis when the model is down.
        """
        self.engine_used = "agent"
        if not parsed_files:
            return ReviewResult(
                status="success", critical_issues=[], warnings=[], suggestions=[]
            )

        if args.base and args.head:
            source = RepoSource.for_diff_mode("range", head=args.head)
        else:
            source = RepoSource.for_diff_mode(args.mode or "staged")
        tools = AgentTools(self.config, source, self.parser, parsed_files)
        agent = AgentReviewer(self.config, trace=self.trace, trace_llm=self.trace_llm)
        result = agent.review(tools)
        if result.status == "success":
            return result

        print(
            f"Agent review failed ({result.status}): {redact(str(result.raw_response))[0]}. "
            "Falling back to the classic engine.",
            file=sys.stderr,
        )
        self.engine_used = "agent->classic"
        fallback = self.reviewer.review_diff(diff_content)
        fallback.agent_stats = {
            **(result.agent_stats or {}),
            "fallback": "classic",
            "fallback_reason": result.raw_response,
        }
        return fallback

    def _output_results(self, result: ReviewResult, args):
        """Output review results in specified format."""

        if args.format == "json":
            output = self._format_json_output(result, args)
            print(json.dumps(output, indent=2))
        else:
            output = self._format_text_output(result, args.verbose)
            print(output)

    def _format_json_output(self, result: ReviewResult, args=None) -> Dict[str, Any]:
        """Format results as JSON."""
        return {
            "status": result.status,
            "review_outcome": result.review_outcome,
            "critical_issues": result.critical_issues,
            "warnings": result.warnings,
            "suggestions": result.suggestions,
            "code_suggestions": [
                {
                    "file": cs.file,
                    "line_start": cs.line_start,
                    "line_end": cs.line_end,
                    "description": cs.description,
                    "suggested_code": cs.suggested_code,
                }
                for cs in result.code_suggestions
            ],
            "fallback_used": result.fallback_used,
            "redacted_count": result.redacted_count,
            "engine": self.engine_used,
            "agent_stats": result.agent_stats,
            "exit_code": self._get_exit_code(result, args),
        }

    def _format_text_output(self, result: ReviewResult, verbose: bool = False) -> str:
        """Format results as human-readable text."""
        lines = []

        # Status indicator
        if result.status == "skipped":
            lines.append("⏭️ Review Skipped (token limit exceeded)")
        elif result.status == "model_unavailable":
            lines.append("🔴 LLM Model Unavailable")
        elif result.critical_issues:
            lines.append("❌ Critical Issues Found")
        elif result.warnings:
            lines.append("⚠️ Warnings Found")
        else:
            lines.append("✅ No Issues Found")

        lines.append("")

        # Critical issues
        if result.critical_issues:
            lines.append("🚨 CRITICAL ISSUES:")
            for issue in result.critical_issues:
                lines.append(f"   • {issue}")
            lines.append("")

        # Warnings
        if result.warnings:
            lines.append("⚠️ WARNINGS:")
            for warning in result.warnings:
                lines.append(f"   • {warning}")
            lines.append("")

        # Suggestions
        if result.suggestions:
            lines.append("💡 SUGGESTIONS:")
            for suggestion in result.suggestions:
                lines.append(f"   • {suggestion}")
            lines.append("")

        # Code suggestions
        if result.code_suggestions:
            lines.append("🔧 CODE SUGGESTIONS:")
            for cs in result.code_suggestions:
                if cs.line_end != cs.line_start:
                    loc = f"{cs.file}:{cs.line_start}-{cs.line_end}"
                else:
                    loc = f"{cs.file}:{cs.line_start}"
                lines.append(f"   {loc}: {cs.description}")
                for code_line in cs.suggested_code.split("\n"):
                    lines.append(f"     {code_line}")
                lines.append("")

        if result.redacted_count:
            lines.append(
                f"🔒 {result.redacted_count} value(s) that look like secrets are hidden."
            )
            lines.append("")

        # Status information
        if verbose:
            lines.append("📊 Status Information:")
            llm_status = "completed" if result.status == "success" else result.status
            lines.append(f"   • LLM Review: {llm_status}")
            outcome_icons = {"critical": "🔴", "warnings": "🟡", "success": "🟢"}
            outcome_icon = outcome_icons.get(result.review_outcome, "")
            lines.append(
                f"   • Code Review Outcome: {outcome_icon} {result.review_outcome}"
            )
            lines.append(f"   • Engine: {self.engine_used}")
            stats = result.agent_stats
            if stats and "steps" in stats:
                lines.append(
                    f"   • Agent: {stats['steps']} step(s), {stats['tool_calls']} "
                    f"tool call(s), {stats['tokens']} tokens, {stats['duration_sec']}s"
                )
            if result.fallback_used:
                lines.append("   • Fallback Analysis: Yes")
            if result.total_chunks > 0:
                lines.append(
                    f"   • Chunks Reviewed: {result.chunks_reviewed}/{result.total_chunks}"
                )
            lines.append("")

        return "\n".join(lines)

    def _run_offline_review(self, args) -> ReviewResult:
        """Run static analysis only, without LLM. Forces docstring checks."""
        from static_analyzer import StaticAnalyzer

        # Get raw git diff (StaticAnalyzer expects raw format with +++ headers)
        if args.base and args.head:
            raw_diff = self.parser.get_diff("range", args.base, args.head)
        elif args.mode:
            raw_diff = self.parser.get_diff(args.mode)
        else:
            raw_diff = self.parser.get_diff("staged")

        if args.verbose:
            parsed_files = self.parser.parse_diff(raw_diff)
            if parsed_files:
                print(f"Analyzing {len(parsed_files)} file(s):", file=sys.stderr)
                for file_data in parsed_files:
                    print(
                        f"  - {file_data['path']} ({file_data['type']})",
                        file=sys.stderr,
                    )
                print("", file=sys.stderr)

        original_value = self.config.get("review.check_docstrings", True)
        self.config.config.setdefault("review", {})["check_docstrings"] = True

        analyzer = StaticAnalyzer(self.config)
        result = analyzer.analyze_diff(raw_diff)

        self.config.config["review"]["check_docstrings"] = original_value
        return result

    def _get_exit_code(self, result: ReviewResult, args=None) -> int:
        """Get exit code from results and the --fail-on policy.

        With fail_on "none" (default) an advisory review always exits 0.
        Otherwise: 5 skipped, 3 model unavailable, 1 failing findings,
        2 non-failing warnings, 0 clean.
        """
        fail_on = getattr(args, "fail_on", None) or "none"
        if fail_on == "none":
            return 0
        if result.status == "skipped":
            return 5  # Review skipped due to token limit
        elif result.status == "model_unavailable":
            return 3  # Model unavailable, static fallback used
        elif result.critical_issues or (result.warnings and fail_on == "warnings"):
            return 1
        elif result.warnings:
            return 2
        else:
            return 0


def main():
    """Main entry point."""
    cli = ReviewCLI(trace=False, trace_llm=False)
    exit_code = cli.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
