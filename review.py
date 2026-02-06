#!/usr/bin/env python3
"""
CLI interface for LLM code review system.
Supports multiple review modes and output formats.
"""

import argparse
import json
import logging
import sys
from typing import Dict, Any
from pathlib import Path
from config import ReviewConfig
from diff_parser import DiffParser
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

    def run(self, args=None):
        """Run CLI with provided arguments."""
        parser = self._create_parser()
        parsed_args = parser.parse_args(args)

        # Setup logging based on verbosity
        setup_logging(getattr(parsed_args, "verbose", False))

        # Update trace mode if specified
        self.trace = getattr(parsed_args, "trace", False)
        self.trace_llm = getattr(parsed_args, "trace_llm", False)
        self.reviewer.trace = self.trace
        self.reviewer.trace_llm = self.trace_llm

        # Handle mutually exclusive --offline and --test-connection
        if parsed_args.offline and parsed_args.test_connection:
            print(
                "Error: --offline and --test-connection are mutually exclusive.",
                file=sys.stderr,
            )
            return 4

        # Handle test-connection before validation
        if parsed_args.test_connection:
            if not self._validate_config():
                return 4  # Configuration error

            if self.reviewer.test_connection():
                print("✅ Connection to LLM successful")
                return 0
            else:
                print("❌ Connection to LLM failed")
                return 1

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
            if parsed_args.offline:
                result = self._run_offline_review(parsed_args)
            else:
                diff_content = self._get_diff_content(parsed_args)
                result = self.reviewer.review_diff(diff_content)

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
  python review.py --mode all --strict               # Review all with strict mode
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
            "--strict",
            action="store_true",
            help="Block commit on any issues (including warnings)",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Verbose output with additional context",
        )
        parser.add_argument(
            "--trace",
            action="store_true",
            help="Trace output showing LLM queries and tool usage",
        )
        parser.add_argument(
            "--trace-llm",
            action="store_true",
            help="Dump full LLM prompts and responses to stderr",
        )
        parser.add_argument(
            "--offline",
            action="store_true",
            help="Run static analysis only, without LLM (forces docstring checks)",
        )

        # Utility commands
        parser.add_argument(
            "--test-connection", action="store_true", help="Test connection to LLM API"
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

    def _get_diff_content(self, args) -> str:
        """Get diff content based on arguments."""
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

        return formatted_diff

    def _output_results(self, result: ReviewResult, args):
        """Output review results in specified format."""

        if args.format == "json":
            output = self._format_json_output(result)
            print(json.dumps(output, indent=2))
        else:
            output = self._format_text_output(result, args.verbose)
            print(output)

    def _format_json_output(self, result: ReviewResult) -> Dict[str, Any]:
        """Format results as JSON."""
        return {
            "status": result.status,
            "review_outcome": result.review_outcome,
            "critical_issues": result.critical_issues,
            "warnings": result.warnings,
            "suggestions": result.suggestions,
            "fallback_used": result.fallback_used,
            "exit_code": self._get_exit_code(result),
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
        """Get appropriate exit code based on results."""
        if result.status == "skipped":
            return 5  # Review skipped due to token limit
        elif result.status == "model_unavailable":
            return 3  # Model unavailable, allow commit with warning
        elif result.critical_issues:
            return 1  # Critical issues, block commit
        elif result.warnings and (args and args.strict):
            return 1  # Warnings in strict mode, block commit
        elif result.warnings:
            return 2  # Warnings, allow commit
        else:
            return 0  # Success


def main():
    """Main entry point."""
    cli = ReviewCLI(trace=False, trace_llm=False)
    exit_code = cli.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
