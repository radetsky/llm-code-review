"""
Read-only tools exposed to the review agent.

Every tool takes a dict of arguments and returns a plain string. Tools never
raise: failures are returned as "Error: ..." so the model can recover.
No shell is used; all repository access goes through RepoSource.
"""

import re
from collections.abc import Callable
from typing import Any

from diff_parser import DiffParser, RepoAccessError, RepoSource

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_LINE_CHARS = 300
MAX_FIND_RESULTS = 100


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOL_SPECS: list[dict] = [
    _fn(
        "list_changed_files",
        "List files changed in the reviewed diff with added/removed line counts.",
        {},
        [],
    ),
    _fn(
        "get_diff",
        "Get the numbered diff of one changed file.",
        {"path": {"type": "string", "description": "Repository-relative path"}},
        ["path"],
    ),
    _fn(
        "read_file",
        "Read a file (optionally a line range). Lines are prefixed with numbers.",
        {
            "path": {"type": "string"},
            "start_line": {"type": "integer", "description": "1-based, inclusive"},
            "end_line": {"type": "integer", "description": "1-based, inclusive"},
        },
        ["path"],
    ),
    _fn(
        "grep",
        "Search the repository with an extended regular expression.",
        {
            "pattern": {"type": "string"},
            "path": {
                "type": "string",
                "description": "Optional directory or file to limit the search",
            },
        },
        ["pattern"],
    ),
    _fn(
        "find_files",
        "Find files by glob pattern, e.g. '*.py' or 'test_*.py'.",
        {"pattern": {"type": "string"}},
        ["pattern"],
    ),
    _fn(
        "find_definition",
        "Find where a function, class, struct, type or constant is defined.",
        {"name": {"type": "string", "description": "Identifier name"}},
        ["name"],
    ),
    _fn(
        "git_log",
        "Show recent commits, optionally only those touching a path.",
        {
            "path": {"type": "string"},
            "max_count": {"type": "integer", "description": "1-50, default 10"},
        },
        [],
    ),
    _fn(
        "git_blame",
        "Show who last changed each line in a range (at most 200 lines).",
        {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        ["path", "start_line", "end_line"],
    ),
]


class ToolError(Exception):
    """Invalid tool arguments; the message is returned to the model."""


class AgentTools:
    """Dispatches tool calls against one repository snapshot."""

    def __init__(
        self,
        config,
        source: RepoSource,
        parser: DiffParser,
        parsed_files: list[dict[str, Any]],
    ):
        self.config = config
        self.source = source
        self.parser = parser
        self.parsed_files = parsed_files
        self._handlers: dict[str, Callable[[dict], str]] = {
            "list_changed_files": self._list_changed_files,
            "get_diff": self._get_diff,
            "read_file": self._read_file,
            "grep": self._grep,
            "find_files": self._find_files,
            "find_definition": self._find_definition,
            "git_log": self._git_log,
            "git_blame": self._git_blame,
        }

    @property
    def specs(self) -> list[dict]:
        """OpenAI-style tool definitions."""
        return TOOL_SPECS

    @property
    def max_chars(self) -> int:
        return int(self.config.get("agent.max_tool_output_chars", 8000))

    def call(self, name: str, arguments: Any) -> str:
        """Run a tool. Always returns a string, never raises."""
        handler = self._handlers.get(name)
        if handler is None:
            known = ", ".join(sorted(self._handlers))
            return f"Error: unknown tool '{name}'. Available tools: {known}"
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return "Error: tool arguments must be a JSON object"
        try:
            return self._truncate(handler(arguments))
        except ToolError as e:
            return f"Error: {e}"
        except RepoAccessError as e:
            return f"Error: {e}"
        except FileNotFoundError:
            return "Error: file not found"
        except (RuntimeError, ValueError) as e:
            return f"Error: {e}"

    # -- helpers -----------------------------------------------------------

    def _truncate(self, text: str) -> str:
        limit = self.max_chars
        if len(text) <= limit:
            return text
        return (
            text[:limit]
            + f"\n[output truncated: showing {limit} of {len(text)} chars; "
            "narrow the request]"
        )

    @staticmethod
    def _str_arg(args: dict, key: str, required: bool = True) -> str:
        value = args.get(key)
        if value is None or value == "":
            if required:
                raise ToolError(f"missing required argument '{key}'")
            return ""
        if not isinstance(value, str):
            raise ToolError(f"argument '{key}' must be a string")
        return value

    @staticmethod
    def _int_arg(args: dict, key: str, default: int | None = None) -> int | None:
        value = args.get(key)
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            raise ToolError(f"argument '{key}' must be an integer")
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ToolError(f"argument '{key}' must be an integer")

    @staticmethod
    def _clip_line(text: str) -> str:
        if len(text) > MAX_LINE_CHARS:
            return text[:MAX_LINE_CHARS] + "..."
        return text

    def _format_matches(self, matches: list[dict]) -> str:
        if not matches:
            return "No matches."
        return "\n".join(
            f"{m['path']}:{m['line']}: {self._clip_line(m['text'])}" for m in matches
        )

    # -- tools -------------------------------------------------------------

    def _list_changed_files(self, args: dict) -> str:
        if not self.parsed_files:
            return "No changed files."
        lines = []
        for f in self.parsed_files:
            added = sum(len(h["added_lines"]) for h in f["hunks"])
            removed = sum(len(h["removed_lines"]) for h in f["hunks"])
            lines.append(f"{f['path']} ({f['type']}) +{added} -{removed}")
        return "\n".join(lines)

    def _get_diff(self, args: dict) -> str:
        path = self._str_arg(args, "path")
        for f in self.parsed_files:
            if f["path"] == path:
                return self.parser.format_for_llm([f])
        raise ToolError(f"'{path}' is not in the changed files list")

    def _read_file(self, args: dict) -> str:
        path = self._str_arg(args, "path")
        start = self._int_arg(args, "start_line")
        end = self._int_arg(args, "end_line")
        if start is not None and start < 1:
            raise ToolError("start_line must be >= 1")
        if end is not None and end < (start or 1):
            raise ToolError("end_line must be >= start_line")
        text = self.source.read(path, start=start, end=end)
        if text == "":
            return "(empty)"
        first = start or 1
        lines = text.split("\n")
        # Keep the truncation marker out of the numbering.
        marker = ""
        if lines and lines[-1] == "[truncated]":
            marker = lines.pop()
        numbered = "\n".join(f"{first + i}: {line}" for i, line in enumerate(lines))
        return f"{numbered}\n{marker}" if marker else numbered

    def _grep(self, args: dict) -> str:
        pattern = self._str_arg(args, "pattern")
        path = self._str_arg(args, "path", required=False)
        limit = int(self.config.get("agent.max_grep_matches", 50))
        return self._format_matches(self.source.grep(pattern, path, max_matches=limit))

    def _find_files(self, args: dict) -> str:
        pattern = self._str_arg(args, "pattern")
        found = self.source.find_files(pattern, max_results=MAX_FIND_RESULTS)
        return "\n".join(found) if found else "No files found."

    def _find_definition(self, args: dict) -> str:
        name = self._str_arg(args, "name")
        if not IDENTIFIER_RE.match(name):
            raise ToolError("name must be a plain identifier")
        # POSIX classes only: \s and \b are not portable across git builds.
        boundary = "($|[^A-Za-z0-9_])"
        keywords = (
            "def|class|function|fn|func|struct|enum|trait|interface|type|const|let|var"
        )
        pattern = (
            f"(^|[^A-Za-z0-9_])({keywords})[[:space:]]+{name}{boundary}"
            f"|func[[:space:]]*\\([^)]*\\)[[:space:]]*{name}[[:space:]]*\\("
        )
        limit = int(self.config.get("agent.max_grep_matches", 50))
        matches = self.source.grep(pattern, max_matches=limit)
        if not matches:
            return (
                f"No definition of '{name}' found. "
                "Try grep for a call site or a C/Java-style declaration."
            )
        return self._format_matches(matches)

    def _git_log(self, args: dict) -> str:
        path = self._str_arg(args, "path", required=False)
        count = self._int_arg(args, "max_count", 10)
        entries = self.source.log(path, max_count=count)
        return "\n".join(entries) if entries else "No commits found."

    def _git_blame(self, args: dict) -> str:
        path = self._str_arg(args, "path")
        start = self._int_arg(args, "start_line")
        end = self._int_arg(args, "end_line")
        if start is None or end is None:
            raise ToolError("start_line and end_line are required")
        return self.source.blame(path, start, end)
