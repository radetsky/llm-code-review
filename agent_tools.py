"""
Read-only tools exposed to the review agent.

Every tool takes a dict of arguments and returns a plain string. Tools never
raise: failures are returned as "Error: ..." so the model can recover.
No shell is used; all repository access goes through RepoSource.
"""

import json
import re
from collections.abc import Callable
from typing import Any

from diff_parser import DiffParser, RepoAccessError, RepoSource

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_LINE_CHARS = 300
MAX_FIND_RESULTS = 100
DUPLICATE_PREFIX = "You already got this result earlier in this review"


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
        "List the changed files. Show the number of added and removed lines for each file.",
        {},
        [],
    ),
    _fn(
        "get_diff",
        "Show the diff of one changed file. Each line has its line number.",
        {"path": {"type": "string", "description": "Path from the repository root"}},
        ["path"],
    ),
    _fn(
        "read_file",
        "Read a file. Each line has its line number. If you give no end_line, "
        "the tool returns only the first lines. Give start_line and end_line to "
        "read a specific part. Use narrow ranges of 20 to 80 lines.",
        {
            "path": {"type": "string"},
            "start_line": {
                "type": "integer",
                "description": "First line to read (the first line of a file is 1)",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to read (this line is included)",
            },
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
                "description": "Directory or file to search in. Optional.",
            },
        },
        ["pattern"],
    ),
    _fn(
        "find_files",
        "Find files with a glob pattern, for example '*.py' or 'test_*.py'.",
        {"pattern": {"type": "string"}},
        ["pattern"],
    ),
    _fn(
        "find_definition",
        "Find where a function, class, struct, type or constant is defined.",
        {"name": {"type": "string", "description": "Name of the identifier"}},
        ["name"],
    ),
    _fn(
        "git_log",
        "Show the latest commits. Give a path to show only the commits that "
        "change this path.",
        {
            "path": {"type": "string"},
            "max_count": {
                "type": "integer",
                "description": "From 1 to 50. The default is 10.",
            },
        },
        [],
    ),
    _fn(
        "git_blame",
        "Show the last commit for each line in a range. The maximum range is "
        "200 lines.",
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
        self._seen_reads: set[tuple[str, int, int]] = set()
        self._seen_calls: set[tuple[str, str]] = set()
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
        return int(self.config.get("agent.max_tool_output_chars", 32000))

    def mark_given(self, name: str, arguments: dict) -> None:
        """Remember that the model already has the result of this call.

        A later call with the same arguments gets a short note, not the result again.
        """
        self._seen_calls.add((name, json.dumps(arguments, sort_keys=True, default=str)))

    def changed_files_summary(self) -> str:
        """Return the changed files with line counts. This is not a tool call."""
        return self._list_changed_files({})

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
        key = (name, json.dumps(arguments, sort_keys=True, default=str))
        if key in self._seen_calls:
            shown = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
            return (
                f"{DUPLICATE_PREFIX}: {name}({shown}). "
                "Use that result. Do not repeat the call."
            )
        try:
            output = self._truncate(handler(arguments))
            self._seen_calls.add(key)  # Remember only the calls that succeed.
            return output
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
            text[:limit] + f"\n[Output cut: {limit} of {len(text)} characters shown. "
            "Make the request narrower.]"
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

        window = int(self.config.get("agent.read_default_lines", 300))
        scan_limit = int(self.config.get("agent.max_read_scan_bytes", 5_000_000))
        first = start or 1
        wanted_last = end if end is not None else first + window - 1
        part = self.source.read_lines(path, first, wanted_last, scan_limit)

        if part.total == 0:
            return "(The file is empty.)"
        if not part.lines:
            if part.total is not None:
                return f"(No lines in this range. The file has {part.total} lines.)"
            return self._beyond_limit_note(part.scanned)

        last = first + len(part.lines) - 1
        key = (path, first, last)
        if key in self._seen_reads:
            return (
                f"{DUPLICATE_PREFIX}: {path} lines {first}-{last}. "
                "Use that result. Do not read it again."
            )
        self._seen_reads.add(key)

        text = "\n".join(f"{first + i}: {line}" for i, line in enumerate(part.lines))
        if part.total is not None:
            if end is None and last < part.total:
                text += (
                    f"\n[Lines {first}-{last} of {part.total} shown. Call read_file "
                    "with start_line and end_line to read other parts.]"
                )
        elif last < wanted_last:
            text += "\n" + self._beyond_limit_note(part.scanned)
        elif end is None:
            text += (
                f"\n[Lines {first}-{last} shown. The file has more lines. Call "
                "read_file with start_line and end_line to read other parts.]"
            )
        return text

    @staticmethod
    def _beyond_limit_note(scanned: int) -> str:
        return (
            "[The file is larger than the read limit. "
            f"Lines after line {scanned} are not available.]"
        )

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
                "Use grep to find a call, or a C or Java declaration."
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
