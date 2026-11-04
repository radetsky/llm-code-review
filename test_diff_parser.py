"""Tests for DiffParser.parse_diff and format_for_llm."""

from unittest.mock import MagicMock

import pytest

from diff_parser import DiffParser


@pytest.fixture()
def parser() -> DiffParser:
    """Return a DiffParser with a minimal stub config."""
    config = MagicMock()
    config.get.return_value = []
    return DiffParser(config)


MULTI_FILE_DIFF = """\
diff --git a/Cargo.toml b/Cargo.toml
new file mode 100644
--- /dev/null
+++ b/Cargo.toml
@@ -0,0 +1,4 @@
+[package]
+name = "did_proto"
+version = "0.1.0"
+edition = "2021"
diff --git a/build.rs b/build.rs
new file mode 100644
--- /dev/null
+++ b/build.rs
@@ -0,0 +1,3 @@
+fn main() {
+    tonic_build::configure().compile(&[], &[]).unwrap();
+}
diff --git a/src/lib.rs b/src/lib.rs
new file mode 100644
--- /dev/null
+++ b/src/lib.rs
@@ -0,0 +1,2 @@
+pub mod gen;
+pub use gen::*;
"""

SINGLE_FILE_DIFF = """\
diff --git a/main.py b/main.py
--- a/main.py
+++ b/main.py
@@ -1,3 +1,4 @@
 def hello():
+    print("hello")
     pass
"""

DELETED_BETWEEN_DIFF = """\
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-line one
-line two
diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+x = 1
+y = 2
"""


def _path_to_hunks(files: list, path: str) -> list:
    """Return hunks for a given file path."""
    for f in files:
        if f["path"] == path:
            return f["hunks"]
    raise KeyError(f"File not found: {path}")


def _added_contents(hunks: list) -> list[str]:
    """Flatten all added_lines content strings from a list of hunks."""
    return [entry["content"] for hunk in hunks for entry in hunk["added_lines"]]


class TestMultiFileAttribution:
    """Each file must carry its own content — not a neighbour's."""

    def test_file_count(self, parser: DiffParser) -> None:
        """Three files in diff → three file dicts returned."""
        files = parser.parse_diff(MULTI_FILE_DIFF)
        paths = [f["path"] for f in files]
        assert paths == ["Cargo.toml", "build.rs", "src/lib.rs"]

    def test_cargo_toml_content(self, parser: DiffParser) -> None:
        """Cargo.toml must contain package metadata, not build.rs code."""
        files = parser.parse_diff(MULTI_FILE_DIFF)
        hunks = _path_to_hunks(files, "Cargo.toml")
        assert len(hunks) == 1
        contents = _added_contents(hunks)
        assert contents[0] == "[package]"
        assert not any("fn main" in c for c in contents)

    def test_build_rs_content(self, parser: DiffParser) -> None:
        """build.rs must start with fn main, not Cargo.toml metadata."""
        files = parser.parse_diff(MULTI_FILE_DIFF)
        hunks = _path_to_hunks(files, "build.rs")
        assert len(hunks) == 1
        contents = _added_contents(hunks)
        assert contents[0] == "fn main() {"
        assert not any("[package]" in c for c in contents)

    def test_lib_rs_content(self, parser: DiffParser) -> None:
        """src/lib.rs must contain pub mod gen, not build.rs code."""
        files = parser.parse_diff(MULTI_FILE_DIFF)
        hunks = _path_to_hunks(files, "src/lib.rs")
        assert len(hunks) == 1
        contents = _added_contents(hunks)
        assert contents[0] == "pub mod gen;"
        assert not any("fn main" in c for c in contents)

    def test_no_extra_hunks(self, parser: DiffParser) -> None:
        """No file should inherit leftover hunks from a previous file."""
        files = parser.parse_diff(MULTI_FILE_DIFF)
        for f in files:
            assert len(f["hunks"]) == 1, (
                f"File {f['path']} has {len(f['hunks'])} hunks, expected 1"
            )


class TestSingleFile:
    """Single-file diff must still work correctly after the refactor."""

    def test_single_file_parsed(self, parser: DiffParser) -> None:
        files = parser.parse_diff(SINGLE_FILE_DIFF)
        assert len(files) == 1
        assert files[0]["path"] == "main.py"

    def test_single_file_added_line(self, parser: DiffParser) -> None:
        files = parser.parse_diff(SINGLE_FILE_DIFF)
        contents = _added_contents(files[0]["hunks"])
        assert '    print("hello")' in contents


class TestDeletedFileBetween:
    """A deleted file between two normal files must not bleed content."""

    def test_deleted_file_no_added_lines(self, parser: DiffParser) -> None:
        files = parser.parse_diff(DELETED_BETWEEN_DIFF)
        old_file = next((f for f in files if f["path"] == "old.txt"), None)
        if old_file is not None:
            assert _added_contents(old_file["hunks"]) == []

    def test_new_py_gets_correct_content(self, parser: DiffParser) -> None:
        files = parser.parse_diff(DELETED_BETWEEN_DIFF)
        hunks = _path_to_hunks(files, "new.py")
        contents = _added_contents(hunks)
        assert contents == ["x = 1", "y = 2"]


# Diff that mirrors the real-world false-positive trigger: two additions
# separated by an unchanged line inside the same hunk.
INTERLEAVED_DIFF = """\
diff --git a/status.rs b/status.rs
--- a/status.rs
+++ b/status.rs
@@ -13,7 +13,9 @@
     DownloadFailed {},
-    /// Checksum or minisign signature does not match the manifest.
+    /// Artifact checksum or the artifact's own minisign signature is invalid.
     VerificationFailed {},
+    /// The detached manifest signature (latest.json.sig) is missing or invalid.
+    ManifestVerificationFailed {},
     /// Installer could not be launched.
"""


class TestFormatForLLMOrdering:
    """format_for_llm must render lines in their physical diff order."""

    def test_interleaved_lines_are_in_physical_order(self, parser: DiffParser) -> None:
        """Interior context must appear between the two added blocks, not after them.

        The rendered output for the interleaved diff should follow physical line
        order so that the LLM does not see two doc-comments back-to-back with
        no enum variant between them.
        """
        parser.config.get.return_value = 10
        files = parser.parse_diff(INTERLEAVED_DIFF)
        rendered = parser.format_for_llm(files)
        lines = [ln for ln in rendered.splitlines() if ln.strip()]

        # Locate the rendered positions of the three key lines.
        removed_idx = next(
            i for i, ln in enumerate(lines) if ln.startswith("- ") and "Checksum" in ln
        )
        context_idx = next(
            i for i, ln in enumerate(lines) if "VerificationFailed" in ln
        )
        added_manifest_idx = next(
            i
            for i, ln in enumerate(lines)
            if ln.startswith("+ ") and "ManifestVerificationFailed" in ln
        )

        # Physical order: removed doc, context variant, added doc, added variant
        assert removed_idx < context_idx < added_manifest_idx, (
            f"Line order wrong: removed={removed_idx}, "
            f"context={context_idx}, added_manifest={added_manifest_idx}\n"
            f"Rendered:\n{rendered}"
        )

    def test_new_file_line_numbers_are_monotonic(self, parser: DiffParser) -> None:
        """New-file (context and added) line numbers must increase monotonically."""
        parser.config.get.return_value = 10
        files = parser.parse_diff(INTERLEAVED_DIFF)
        rendered = parser.format_for_llm(files)

        new_file_nums = []
        for line in rendered.splitlines():
            if line.startswith("  ") or line.startswith("+ "):
                try:
                    num = int(line.split(":")[0].strip())
                    new_file_nums.append(num)
                except ValueError:
                    pass

        assert new_file_nums == sorted(new_file_nums), (
            f"New-file line numbers are not monotonic: {new_file_nums}"
        )

    def test_trim_context_leading_trailing(self, parser: DiffParser) -> None:
        """_trim_context keeps at most max_context leading and trailing context lines."""
        lines = (
            [{"kind": "context", "line": i, "content": f"ctx{i}"} for i in range(1, 6)]
            + [
                {"kind": "added", "line": 6, "content": "new"},
            ]
            + [
                {"kind": "context", "line": i, "content": f"ctx{i}"}
                for i in range(7, 12)
            ]
        )
        trimmed = parser._trim_context(lines, max_context=2)
        leading_ctx = [
            x for x in trimmed if x["content"].startswith("ctx") and x["line"] < 6
        ]
        trailing_ctx = [
            x for x in trimmed if x["content"].startswith("ctx") and x["line"] >= 7
        ]
        assert len(leading_ctx) == 2
        assert len(trailing_ctx) == 2
        assert any(x["kind"] == "added" for x in trimmed)
