"""
Static analyzer for fallback when LLM is unavailable.
Provides basic security and code quality analysis.
"""

import re
from typing import List, Dict, Any


class StaticAnalyzer:
    """Static code analysis for basic security checks."""

    # Patterns for detecting function/class definitions and their docstrings
    # Each entry: (definition_regex, docstring_opener_regex, name_group_index)
    DOCSTRING_PATTERNS = {
        ".py": {
            "definition": re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)"),
            "docstring": re.compile(r'^\s*(?:"""|\'\'\'|r"""|r\'\'\')'),
            "position": "after",
        },
        ".js": {
            "definition": re.compile(
                r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:"
                r"function\s+(\w+)"
                r"|class\s+(\w+)"
                r"|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function\s*[\s(]|\([^)]*\)\s*=>|[a-zA-Z_$]\w*\s*=>)"
                r"|(?!if|else|for|while|switch|catch|do|return|throw|new|typeof|instanceof|void|delete|await|yield)(\w+)\s*\([^)]*\)\s*\{"
                r")"
            ),
            "docstring": re.compile(r"^\s*/\*\*"),
            "position": "before",
        },
        ".java": {
            "definition": re.compile(
                r"^\s*(?:public|private|protected|static|final|abstract|synchronized|default|strictfp|\s)*"
                r"(?:<[^>]+>\s*)?"
                r"(?:class|interface|enum|record|@interface|void|int|String|boolean|long|double|float|char|byte|short|[A-Z]\w*)"
                r"(?:\s*\[\])*"
                r"\s+(\w+)\s*[\(<{]"
            ),
            "docstring": re.compile(r"^\s*/\*\*"),
            "position": "before",
        },
        ".c": {
            "definition": re.compile(
                r"^\s*(?:(?:static|inline|const|volatile|extern|unsigned|signed|virtual|explicit)\s+)*"
                r"(?:void|bool|int|char|float|double|long|short|size_t|ssize_t|struct\s+\w+|enum\s+\w+|union\s+\w+|class\s+\w+|\w+_t|\w+::\w+)"
                r"(?:\s*\*+|\s*&+|\s+)*"
                r"\s*(\w+)\s*\("
            ),
            "docstring": re.compile(r"^\s*(?:/\*\*|///)"),
            "position": "before",
        },
        ".go": {
            "definition": re.compile(
                r"^\s*func\s+(?:\(\s*\w+\s+\*?[\w.]+\)\s+)?(\w+)\s*(?:\[[^\]]*\])?\s*\("
            ),
            "docstring": re.compile(r"^\s*//"),
            "position": "before",
        },
        ".rs": {
            "definition": re.compile(
                r"^\s*(?:pub\s*(?:\([^)]*\)\s*)?)?(?:(?:async|unsafe|const|default)\s+)*(?:extern\s+\"[^\"]*\"\s+)?(?:fn|struct|enum|trait|impl|type|mod)\s+(\w+)"
            ),
            "docstring": re.compile(r"^\s*///"),
            "position": "before",
        },
    }

    # Extension aliases mapping to canonical patterns
    _EXT_ALIASES = {
        ".ts": ".js",
        ".jsx": ".js",
        ".tsx": ".js",
        ".cpp": ".c",
        ".h": ".c",
    }

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

        # Docstring checks
        if self.config.get("review.check_docstrings", True):
            suggestions.extend(self._check_docstrings(added_lines))

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

    def _get_docstring_patterns(self, ext: str) -> dict | None:
        """Get docstring patterns for a file extension, resolving aliases."""
        canonical = self._EXT_ALIASES.get(ext, ext)
        return self.DOCSTRING_PATTERNS.get(canonical)

    def _count_body_lines(self, lines: List[str], start_index: int, ext: str) -> int:
        """Count the number of body lines for a definition starting at start_index."""
        canonical = self._EXT_ALIASES.get(ext, ext)

        if canonical == ".py":
            # Indentation-based: count subsequent non-blank lines with strictly
            # greater indentation than the definition line.
            def_line = lines[start_index]
            def_indent = len(def_line) - len(def_line.lstrip())
            count = 0
            for j in range(start_index + 1, len(lines)):
                stripped = lines[j].strip()
                if not stripped:
                    continue
                line_indent = len(lines[j]) - len(lines[j].lstrip())
                if line_indent <= def_indent:
                    break
                count += 1
            return count
        else:
            # Brace languages: track { } depth.
            depth = 0
            started = False
            count = 0
            for j in range(start_index, len(lines)):
                line = lines[j]
                for ch in line:
                    if ch == "{":
                        depth += 1
                        started = True
                    elif ch == "}":
                        depth -= 1
                if started and j > start_index:
                    if lines[j].strip():
                        count += 1
                if started and depth <= 0:
                    break
            return count

    def _check_docstrings(self, added_lines: List[Dict[str, str]]) -> List[str]:
        """Check added lines for functions/classes missing docstrings."""
        suggestions = []

        # Group added lines by file, preserving order
        files: Dict[str, List[str]] = {}
        for line_info in added_lines:
            fp = line_info["file"]
            if fp not in files:
                files[fp] = []
            files[fp].append(line_info["content"])

        for file_path, lines in files.items():
            # Determine file extension
            ext = ""
            dot_idx = file_path.rfind(".")
            if dot_idx != -1:
                ext = file_path[dot_idx:]

            patterns = self._get_docstring_patterns(ext)
            if not patterns:
                continue

            def_re = patterns["definition"]
            doc_re = patterns["docstring"]
            position = patterns.get("position", "after")

            for i, line in enumerate(lines):
                match = def_re.match(line)
                if not match:
                    continue

                # Extract function/class name from first non-None group
                name = next((g for g in match.groups() if g is not None), "unknown")

                has_docstring = False
                if position == "after":
                    # Python: docstring on the line(s) after the definition
                    for j in range(i + 1, min(i + 3, len(lines))):
                        if not lines[j].strip():
                            continue
                        if doc_re.match(lines[j]):
                            has_docstring = True
                        break
                else:
                    # Other languages: doc comment on the line(s) before the definition
                    for j in range(i - 1, max(i - 4, -1), -1):
                        if not lines[j].strip():
                            continue
                        if doc_re.match(lines[j]):
                            has_docstring = True
                        break

                if not has_docstring:
                    min_lines = self.config.get("review.docstring_min_lines", 0)
                    if min_lines > 0:
                        body_lines = self._count_body_lines(lines, i, ext)
                        if body_lines < min_lines:
                            continue
                    suggestions.append(f"{file_path}: Missing docstring for '{name}'")

        return suggestions
