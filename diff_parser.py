"""
Git diff parser for extracting and structuring code changes.
"""

import re
import subprocess
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

        lines = diff_text.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # File header
            if line.startswith("diff --git"):
                if current_file:
                    files.append(current_file)

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
            elif line.startswith("---"):
                pass  # Source file
            elif line.startswith("+++"):
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
                elif line.startswith("-"):
                    # Removed line — only in old file
                    current_hunk["removed_lines"].append(
                        {"line": old_line_num, "content": line[1:]}
                    )
                    old_line_num += 1
                elif line.startswith("+"):
                    # Added line — only in new file
                    current_hunk["added_lines"].append(
                        {"line": new_line_num, "content": line[1:]}
                    )
                    new_line_num += 1

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
