"""
Static analyzer for fallback when LLM is unavailable.
Provides basic security and code quality analysis.
"""

import re
from typing import List, Dict, Any


class StaticAnalyzer:
    """Static code analysis for basic security checks."""

    def __init__(self, config):
        self.config = config

    def analyze_diff(self, diff_content: str) -> Any:
        """Analyze diff content for security issues."""
        from review_core import ReviewResult

        critical_issues = []
        warnings = []
        suggestions = []

        # Extract added lines from diff
        added_lines = self._extract_added_lines(diff_content)

        for line_info in added_lines:
            line = line_info["content"]
            file_path = line_info["file"]

            # Security checks - convert to warnings for static analysis
            # In static analysis mode, we treat everything as warnings to avoid blocking commits
            # when LLM is unavailable
            critical_from_static = []
            critical_from_static.extend(self._check_credentials(line, file_path))
            critical_from_static.extend(self._check_sql_injection(line, file_path))
            critical_from_static.extend(self._check_unsafe_functions(line, file_path))
            critical_from_static.extend(self._check_file_operations(line, file_path))

            # Convert critical issues to warnings for static analysis fallback
            warnings.extend(
                [f"STATIC_ANALYSIS: {issue}" for issue in critical_from_static]
            )

            # Code quality checks
            warnings.extend(self._check_hardcoded_urls(line, file_path))
            warnings.extend(self._check_debug_code(line, file_path))

            # Suggestions
            suggestions.extend(self._suggest_improvements(line, file_path))

        return ReviewResult(
            status="success",
            critical_issues=critical_issues,
            warnings=warnings,
            suggestions=suggestions,
            fallback_used=True,
        )

    def _extract_added_lines(self, diff_content: str) -> List[Dict[str, str]]:
        """Extract added lines from diff with file context."""
        lines = []
        current_file = "unknown"

        for line in diff_content.split("\n"):
            if line.startswith("+++"):
                # Extract file path
                match = re.search(r"b/(.+)$", line)
                if match:
                    current_file = match.group(1)
            elif line.startswith("+") and not line.startswith("+++"):
                lines.append(
                    {
                        "content": line[1:],  # Remove '+' prefix
                        "file": current_file,
                    }
                )

        return lines

    def _check_credentials(self, line: str, file_path: str) -> List[str]:
        """Check for hardcoded credentials."""
        issues = []

        # Common credential patterns
        credential_patterns = [
            r'password\s*=\s*["\'][^"\']+["\']',
            r'api_key\s*=\s*["\'][^"\']+["\']',
            r'secret\s*=\s*["\'][^"\']+["\']',
            r'token\s*=\s*["\'][^"\']+["\']',
            r'["\'][A-Za-z0-9+/]{20,}["\']',  # Base64-like strings
        ]

        for pattern in credential_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                issues.append(f"{file_path}: Hardcoded credential detected")
                break

        return issues

    def _check_sql_injection(self, line: str, file_path: str) -> List[str]:
        """Check for SQL injection vulnerabilities."""
        issues = []

        # SQL injection patterns
        dangerous_patterns = [
            r'execute\s*\(\s*["\'].*\+.*["\']',  # String concatenation in SQL
            r'query\s*\(\s*["\'].*\+.*["\']',  # String concatenation in queries
            r"format.*\{.*\}.*SELECT",  # String formatting with SQL
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                issues.append(f"{file_path}: Potential SQL injection vulnerability")
                break

        return issues

    def _check_unsafe_functions(self, line: str, file_path: str) -> List[str]:
        """Check for unsafe function usage."""
        issues = []

        unsafe_functions = [
            "eval(",
            "exec(",
            "system(",
            "subprocess.call.*shell=True",
            "os.system(",
            "__import__(",
            "input(",  # In some contexts
        ]

        for func in unsafe_functions:
            if func in line:
                issues.append(
                    f"{file_path}: Unsafe function '{func.split('(')[0]}' detected"
                )
                break

        return issues

    def _check_file_operations(self, line: str, file_path: str) -> List[str]:
        """Check for unsafe file operations."""
        issues = []

        # File operations without validation
        dangerous_patterns = [
            r'open\s*\(\s*["\'][^"\']*["\'].*\+',  # File path with concatenation
            r"open\s*\(\s*.*input.*\)",  # Using input in file path
            r"os\.remove\s*\(\s*.*\+",  # Path concatenation in delete
            r"shutil\.rmtree\s*\(\s*.*\+",  # Path concatenation in delete
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, line):
                issues.append(f"{file_path}: Unsafe file operation detected")
                break

        return issues

    def _check_hardcoded_urls(self, line: str, file_path: str) -> List[str]:
        """Check for hardcoded URLs."""
        warnings = []

        url_patterns = [
            r"https?://[^/\s]+",
            r"ftp://[^/\s]+",
        ]

        for pattern in url_patterns:
            if re.search(pattern, line):
                # Skip localhost and common development URLs
                if not any(
                    skip in line.lower()
                    for skip in ["localhost", "127.0.0.1", "0.0.0.0"]
                ):
                    warnings.append(f"{file_path}: Hardcoded URL detected")
                    break

        return warnings

    def _check_debug_code(self, line: str, file_path: str) -> List[str]:
        """Check for debug code that shouldn't be in production."""
        warnings = []

        debug_patterns = [
            r"print\s*\(",
            r"console\.log\s*\(",
            r"debugger",
            r"pdb\.set_trace",
            r"import\s+pdb",
        ]

        for pattern in debug_patterns:
            if re.search(pattern, line):
                warnings.append(f"{file_path}: Debug code detected")
                break

        return warnings

    def _suggest_improvements(self, line: str, file_path: str) -> List[str]:
        """Suggest code improvements."""
        suggestions = []

        # Suggest environment variables for configuration
        if re.search(
            r'(password|api_key|secret|token)\s*=\s*["\']', line, re.IGNORECASE
        ):
            suggestions.append(
                f"{file_path}: Consider using environment variables for sensitive configuration"
            )

        # Suggest parameterized queries
        if "SELECT" in line and ("+" in line or "%" in line):
            suggestions.append(
                f"{file_path}: Consider using parameterized queries to prevent SQL injection"
            )

        # Suggest input validation
        if "input(" in line:
            suggestions.append(
                f"{file_path}: Add input validation when using user input"
            )

        return suggestions
