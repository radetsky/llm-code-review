"""
Git diff parser for extracting and structuring code changes.
"""

import contextlib
import fnmatch
import os
import posixpath
import re
import subprocess
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


class DiffParser:
    """Parses git diff output into structured format."""

    def __init__(self, config):
        self.config = config

    def get_diff(
        self,
        mode: str = "staged",
        base: Optional[str] = None,
        head: Optional[str] = None,
    ) -> str:
        """Get git diff based on mode."""
        context = self.config.get("output.max_context_lines", 10)
        u_flag = f"-U{context}"
        if mode == "staged":
            return self._run_git(["diff", "--cached", u_flag])
        elif mode == "unstaged":
            return self._run_git(["diff", u_flag])
        elif mode == "all":
            return self._run_git(["diff", "HEAD", u_flag])
        elif mode == "range" and base and head:
            return self._run_git(["diff", f"{base}...{head}", u_flag])
        else:
            raise ValueError(f"Unsupported diff mode: {mode}")

    def _run_git(self, args: List[str]) -> str:
        """Run git command and return output."""
        try:
            result = subprocess.run(
                ["git"] + args, capture_output=True, text=True, check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            if e.returncode == 128 and "not a git repository" in e.stderr:
                raise RuntimeError("Not in a git repository")
            elif "fatal: bad revision" in e.stderr:
                raise RuntimeError("Invalid git reference")
            else:
                raise RuntimeError(f"Git command failed: {e.stderr}")
        except FileNotFoundError:
            raise RuntimeError("Git command not found")

    def parse_diff(self, diff_text: str) -> List[Dict[str, Any]]:
        """Parse diff text into structured list of file changes."""
        if not diff_text.strip():
            return []

        files = []
        current_file = None
        current_hunk = None
        old_line_num = 0
        new_line_num = 0
        old_left = 0  # Old-side lines that the current hunk still needs.
        new_left = 0  # New-side lines that the current hunk still needs.

        lines = diff_text.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # File header
            if line.startswith("diff --git"):
                if current_file:
                    # Add the last hunk to the file that owns it.
                    if current_hunk:
                        current_file["hunks"].append(current_hunk)
                    files.append(current_file)
                current_hunk = None
                old_left = new_left = 0

                # Extract file paths
                match = re.search(r"b/(.+)$", line)
                file_path = match.group(1) if match else "unknown"

                current_file = {
                    "path": file_path,
                    "type": "modified",  # Will be updated by next lines
                    "hunks": [],
                }

            # File operations
            elif line.startswith("new file mode") and current_file:
                current_file["type"] = "added"
            elif line.startswith("deleted file mode") and current_file:
                current_file["type"] = "deleted"
            elif line.startswith("rename from") and current_file:
                current_file["type"] = "renamed"

            # File path lines
            # In a hunk, a line that starts with "---" or "+++" can be content
            # (a removed "--" or an added "++"). It is a header only after the
            # hunk counts reach zero.
            elif line.startswith("---") and not (current_hunk and old_left > 0):
                pass  # Source file
            elif line.startswith("+++") and not (current_hunk and new_left > 0):
                # Target file - extract actual path
                match = re.search(r"b/(.+)$", line)
                if match and current_file:
                    current_file["path"] = match.group(1)

            # Hunk header
            elif line.startswith("@@"):
                if current_hunk and current_file:
                    current_file["hunks"].append(current_hunk)

                # Parse hunk header: @@ -start,count +start,count @@
                match = re.search(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
                if match and current_file:
                    old_start = int(match.group(1))
                    old_count = int(match.group(2) or 1)
                    new_start = int(match.group(3))
                    new_count = int(match.group(4) or 1)

                    old_line_num = old_start
                    new_line_num = new_start
                    old_left = old_count
                    new_left = new_count

                    current_hunk = {
                        "old_start": old_start,
                        "old_count": old_count,
                        "new_start": new_start,
                        "new_count": new_count,
                        "context_before": [],
                        "removed_lines": [],
                        "added_lines": [],
                        "context_after": [],
                    }

            # Content lines
            elif current_hunk:
                if line.startswith(" "):
                    # Context line — exists in both old and new file
                    entry = {"line": new_line_num, "content": line[1:]}
                    if (
                        not current_hunk["added_lines"]
                        and not current_hunk["removed_lines"]
                    ):
                        current_hunk["context_before"].append(entry)
                    else:
                        current_hunk["context_after"].append(entry)
                    old_line_num += 1
                    new_line_num += 1
                    old_left -= 1
                    new_left -= 1
                elif line.startswith("-"):
                    # Removed line — only in old file
                    current_hunk["removed_lines"].append(
                        {"line": old_line_num, "content": line[1:]}
                    )
                    old_line_num += 1
                    old_left -= 1
                elif line.startswith("+"):
                    # Added line — only in new file
                    current_hunk["added_lines"].append(
                        {"line": new_line_num, "content": line[1:]}
                    )
                    new_line_num += 1
                    new_left -= 1

            i += 1

        # Add the last file and hunk
        if current_file:
            if current_hunk:
                current_file["hunks"].append(current_hunk)
            files.append(current_file)

        return self._filter_files(files)

    def _filter_files(self, files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter files based on configuration."""
        filtered_files = []

        for file_data in files:
            file_path = file_data["path"]

            # Skip deleted files for review
            if file_data["type"] == "deleted":
                continue

            # Check if file is supported
            if self.config.is_file_supported(file_path):
                filtered_files.append(file_data)

        return filtered_files

    def format_for_llm(self, parsed_files: List[Dict[str, Any]]) -> str:
        """Format parsed diff for LLM consumption."""
        if not parsed_files:
            return "No code changes to review."

        formatted_sections = []

        for file_data in parsed_files:
            file_path = file_data["path"]
            file_type = file_data["type"]
            hunks = file_data["hunks"]

            formatted_sections.append(f"File: {file_path} ({file_type})")

            for hunk in hunks:
                if hunk["added_lines"] or hunk["removed_lines"]:
                    formatted_sections.append(
                        f"Lines {hunk['new_start']}-{hunk['new_start'] + hunk['new_count'] - 1}:"
                    )

                    max_context = self.config.get("output.max_context_lines", 10)

                    # Context before with line numbers
                    for entry in hunk["context_before"][-max_context:]:
                        formatted_sections.append(
                            f"  {entry['line']}: {entry['content']}"
                        )

                    # Removed lines with old-file line numbers
                    for entry in hunk["removed_lines"]:
                        formatted_sections.append(
                            f"- {entry['line']}: {entry['content']}"
                        )

                    # Added lines with new-file line numbers
                    for entry in hunk["added_lines"]:
                        formatted_sections.append(
                            f"+ {entry['line']}: {entry['content']}"
                        )

                    # Context after with line numbers
                    for entry in hunk["context_after"][:max_context]:
                        formatted_sections.append(
                            f"  {entry['line']}: {entry['content']}"
                        )

                    formatted_sections.append("")  # Empty line for readability

        return "\n".join(formatted_sections)

    def get_changed_files_list(self, mode: str = "staged") -> List[str]:
        """Get list of changed files."""
        if mode == "staged":
            result = self._run_git(["diff", "--cached", "--name-only"])
        elif mode == "unstaged":
            result = self._run_git(["diff", "--name-only"])
        elif mode == "all":
            result = self._run_git(["diff", "HEAD", "--name-only"])
        else:
            raise ValueError(f"Unsupported mode: {mode}")

        files = [f.strip() for f in result.split("\n") if f.strip()]
        return [f for f in files if self.config.is_file_supported(f)]


# Files the agent must never read, even if they are tracked by git.
DENY_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials*",
)


class RepoAccessError(Exception):
    """Raised when a path is outside the repository or is denied."""


@dataclass
class LineSlice:
    """Lines that RepoSource.read_lines returns.

    lines: the requested lines, without line ends.
    first: the number of the first requested line.
    scanned: the number of lines that the method counted.
    total: the number of lines in the file, or None when the file is larger
        than the scan limit.
    """

    lines: list[str]
    first: int
    scanned: int
    total: int | None


class RepoSource:
    """Read-only access to repository files for a given review mode.

    Modes:
        worktree - files on disk (unstaged / all-from-HEAD reviews)
        index    - staged content (``git show :path``)
        rev      - content at a git revision (``git show rev:path``)

    Paths are always repository-relative. Absolute paths, ``..`` segments,
    symlinks and deny-listed files are rejected.
    """

    def __init__(
        self,
        root: str | None = None,
        mode: str = "worktree",
        rev: str | None = None,
        deny_patterns: tuple = DENY_PATTERNS,
    ):
        if mode not in ("worktree", "index", "rev"):
            raise ValueError(f"Unsupported source mode: {mode}")
        if mode == "rev" and not rev:
            raise ValueError("rev is required for mode 'rev'")
        if rev and rev.startswith("-"):
            raise ValueError("Invalid git revision")
        self.mode = mode
        self.rev = rev
        self.deny_patterns = deny_patterns
        top = self._git(["rev-parse", "--show-toplevel"], root or ".").strip()
        self.root = os.path.realpath(top)

    @classmethod
    def for_diff_mode(
        cls, diff_mode: str, head: str | None = None, root: str | None = None
    ) -> "RepoSource":
        """Build a source matching the diff mode used by DiffParser."""
        if diff_mode == "staged":
            return cls(root, "index")
        if diff_mode in ("unstaged", "all"):
            return cls(root, "worktree")
        if diff_mode == "range" and head:
            return cls(root, "rev", rev=head)
        raise ValueError(f"Unsupported diff mode: {diff_mode}")

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _git(args: list[str], cwd: str) -> str:
        try:
            result = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                errors="replace",
                check=True,
                cwd=cwd,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git command failed: {e.stderr.strip()}")
        except FileNotFoundError:
            raise RuntimeError("Git command not found")

    def _run(self, args: list[str], ok_codes: tuple = (0,)) -> str:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            cwd=self.root,
        )
        if result.returncode not in ok_codes:
            raise RuntimeError(f"Git command failed: {result.stderr.strip()}")
        return result.stdout

    def _is_denied(self, rel_path: str) -> bool:
        parts = rel_path.split("/")
        return any(
            fnmatch.fnmatch(part, pattern)
            for part in parts
            for pattern in self.deny_patterns
        )

    def _normalize(self, path: str) -> str:
        """Validate a repository-relative path and return it in POSIX form."""
        if not isinstance(path, str) or "\x00" in path:
            raise RepoAccessError("Invalid path")
        if path in ("", "."):
            return ""
        if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path):
            raise RepoAccessError("Absolute paths are not allowed")
        norm = posixpath.normpath(path.replace("\\", "/"))
        if norm == ".." or norm.startswith("../"):
            raise RepoAccessError("Path escapes the repository")
        if norm == ".git" or norm.startswith(".git/"):
            raise RepoAccessError("Access to .git is not allowed")
        if self._is_denied(norm):
            raise RepoAccessError("Access to this file is denied")
        return norm

    def _tree_ref(self) -> str:
        return self.rev if self.mode == "rev" else ""

    def _entry_mode(self, rel_path: str) -> str | None:
        """Return git file mode (e.g. 100644, 120000) or None if absent."""
        if self.mode == "index":
            out = self._run(["ls-files", "-s", "--", rel_path])
            return out.split()[0] if out.strip() else None
        out = self._run(["ls-tree", self.rev, "--", rel_path])
        return out.split()[0] if out.strip() else None

    # -- public API --------------------------------------------------------

    @contextlib.contextmanager
    def _open_stream(self, path: str):
        """Open a file for reading as a binary stream, after all safety checks.

        The stream gives the file content for the source mode. The caller
        can stop early. This method never loads the whole file.
        """
        rel = self._normalize(path)
        if not rel:
            raise RepoAccessError("A file path is required")

        if self.mode == "worktree":
            full = os.path.join(self.root, rel)
            real = os.path.realpath(full)
            if os.path.islink(full) or not (
                real == self.root or real.startswith(self.root + os.sep)
            ):
                raise RepoAccessError("Symlinks are not allowed")
            # Reject symlinked parent directories as well.
            if os.path.dirname(full) != os.path.dirname(real):
                raise RepoAccessError("Symlinks are not allowed")
            if not os.path.isfile(full):
                raise FileNotFoundError(rel)
            with open(full, "rb") as f:
                yield f
            return

        entry = self._entry_mode(rel)
        if entry is None:
            raise FileNotFoundError(rel)
        if entry == "120000":
            raise RepoAccessError("Symlinks are not allowed")
        if entry not in ("100644", "100755"):
            raise RepoAccessError("Not a regular file")
        spec = f":{rel}" if self.mode == "index" else f"{self.rev}:{rel}"
        proc = subprocess.Popen(
            ["git", "show", spec],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=self.root,
        )
        try:
            yield proc.stdout
        finally:
            proc.kill()  # Stop git when the caller does not read to the end.
            proc.wait()
            proc.stdout.close()

    def read(
        self,
        path: str,
        start: int | None = None,
        end: int | None = None,
        max_bytes: int = 200_000,
    ) -> str:
        """Return file text, optionally limited to 1-based inclusive lines.

        The method reads at most max_bytes bytes. Use read_lines to read
        lines from a large file.
        """
        with self._open_stream(path) as stream:
            raw = stream.read(max_bytes + 1)

        if b"\x00" in raw[:8000]:
            raise RepoAccessError("Binary file")
        truncated = len(raw) > max_bytes
        text = raw[:max_bytes].decode("utf-8", errors="replace")

        if start is not None or end is not None:
            lines = text.split("\n")
            first = max((start or 1) - 1, 0)
            last = end if end is not None else len(lines)
            text = "\n".join(lines[first:last])
        if truncated:
            text += "\n[truncated]"
        return text

    def read_lines(
        self,
        path: str,
        start: int,
        end: int,
        max_scan_bytes: int = 5_000_000,
    ) -> "LineSlice":
        """Return the lines start..end (1-based, included) of a file.

        The method reads the file as a stream and keeps only the requested
        lines. It stops after about max_scan_bytes bytes. If the file is
        larger, the total number of lines is unknown and the lines after the
        scanned part are not available.
        """
        start = max(int(start), 1)
        end = max(int(end), start)
        kept: list[str] = []
        scanned = 0
        complete = False

        def keep(raw_line: bytes) -> None:
            if start <= scanned <= end:
                kept.append(raw_line.decode("utf-8", errors="replace"))

        with self._open_stream(path) as stream:
            buf = stream.read(65536)
            if b"\x00" in buf[:8000]:
                raise RepoAccessError("Binary file")
            bytes_read = len(buf)
            while True:
                pos = 0
                while (i := buf.find(b"\n", pos)) >= 0:
                    scanned += 1
                    keep(buf[pos:i])
                    pos = i + 1
                buf = buf[pos:]
                if bytes_read >= max_scan_bytes:
                    complete = not (buf or stream.read(1))
                    break
                chunk = stream.read(65536)
                if not chunk:
                    complete = True
                    if buf:  # The last line has no newline.
                        scanned += 1
                        keep(buf)
                    break
                bytes_read += len(chunk)
                buf += chunk

        return LineSlice(
            lines=kept,
            first=start,
            scanned=scanned,
            total=scanned if complete else None,
        )

    def list_dir(self, path: str = "") -> list[str]:
        """List tracked entries directly under a directory (dirs end with '/')."""
        rel = self._normalize(path)
        if self.mode == "worktree":
            args = ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        elif self.mode == "index":
            args = ["ls-files", "-z"]
        else:
            args = ["ls-tree", "-r", "--name-only", "-z", self.rev]
        names = [n for n in self._run(args).split("\x00") if n]

        prefix = f"{rel}/" if rel else ""
        entries = set()
        for name in names:
            if not name.startswith(prefix) or self._is_denied(name):
                continue
            head, sep, _ = name[len(prefix) :].partition("/")
            entries.add(prefix + head + ("/" if sep else ""))
        return sorted(entries)

    def find_files(self, pattern: str, max_results: int = 200) -> list[str]:
        """Find files whose path matches a glob pattern (fnmatch)."""
        if self.mode == "worktree":
            args = ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
        elif self.mode == "index":
            args = ["ls-files", "-z"]
        else:
            args = ["ls-tree", "-r", "--name-only", "-z", self.rev]
        names = [n for n in self._run(args).split("\x00") if n]
        matches = [
            n
            for n in names
            if not self._is_denied(n)
            and (
                fnmatch.fnmatch(n, pattern)
                or fnmatch.fnmatch(posixpath.basename(n), pattern)
            )
        ]
        return sorted(matches)[:max_results]

    def grep(
        self,
        pattern: str,
        path: str = "",
        max_matches: int = 100,
    ) -> list[dict[str, Any]]:
        """Search with ``git grep -E``. Returns dicts with path, line, text."""
        if not pattern:
            raise ValueError("pattern is required")
        rel = self._normalize(path)

        args = ["grep", "-n", "-I", "-E", "--no-color", "-z"]
        if self.mode == "index":
            args.append("--cached")
        elif self.mode == "worktree":
            args.append("--untracked")
        args += ["-e", pattern]
        if self.mode == "rev":
            args.append(self.rev)
        args += ["--", rel or "."]

        # git grep exits with 1 when nothing matches.
        out = self._run(args, ok_codes=(0, 1))
        results: list[dict[str, Any]] = []
        for record in out.split("\n"):
            if not record:
                continue
            # With -z, fields are separated by NUL: [rev:]path NUL line NUL text
            fields = record.split("\x00", 2)
            if len(fields) != 3:
                continue
            file_path, line_no, text = fields
            if self.mode == "rev" and file_path.startswith(f"{self.rev}:"):
                file_path = file_path[len(self.rev) + 1 :]
            if self._is_denied(file_path) or not line_no.isdigit():
                continue
            results.append({"path": file_path, "line": int(line_no), "text": text})
            if len(results) >= max_matches:
                break
        return results

    def _history_ref(self) -> str:
        """Revision used for history lookups (HEAD unless reviewing a rev)."""
        return self.rev if self.mode == "rev" else "HEAD"

    def log(self, path: str = "", max_count: int = 20) -> list[str]:
        """Return one-line commit summaries touching a path (or the whole repo)."""
        rel = self._normalize(path)
        count = max(1, min(int(max_count), 50))
        args = [
            "log",
            f"-n{count}",
            "--date=short",
            "--pretty=format:%h %ad %an: %s",
            self._history_ref(),
            "--",
        ]
        if rel:
            args.append(rel)
        out = self._run(args)
        return [line for line in out.split("\n") if line]

    def blame(self, path: str, start: int, end: int, max_lines: int = 200) -> str:
        """Return ``git blame`` output for a 1-based inclusive line range.

        Staged (index) reviews are blamed against HEAD, so uncommitted lines
        are only reported as such in worktree mode.
        """
        rel = self._normalize(path)
        if not rel:
            raise RepoAccessError("A file path is required")
        if start < 1 or end < start:
            raise ValueError("Invalid line range")
        end = min(end, start + max_lines - 1)
        # Reuse read() to enforce symlink/binary/deny checks and existence.
        self.read(rel, start=start, end=end)

        args = ["blame", "-w", "--date=short", "-L", f"{start},{end}"]
        if self.mode != "worktree":
            args.append(self._history_ref())
        args += ["--", rel]
        return self._run(args)
