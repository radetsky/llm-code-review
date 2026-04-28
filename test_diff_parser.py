"""Tests for DiffParser.parse_diff to catch cross-file hunk attribution bugs."""

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
