"""Tests for DiffParser.parse_diff on multi-file diffs."""

from config import ReviewConfig
from diff_parser import DiffParser

TWO_FILES = """\
diff --git a/a.py b/a.py
index 111..222 100644
--- a/a.py
+++ b/a.py
@@ -1,3 +1,3 @@
 line1
-old_a
+new_a
 line3
diff --git a/b.py b/b.py
index 333..444 100644
--- a/b.py
+++ b/b.py
@@ -10,3 +10,3 @@
 ctx
-old_b
+new_b
 ctx2
"""


def parse(text):
    return DiffParser(ReviewConfig()).parse_diff(text)


def summary(files):
    return {
        f["path"]: [
            (
                h["new_start"],
                [e["content"] for e in h["removed_lines"]],
                [e["content"] for e in h["added_lines"]],
            )
            for h in f["hunks"]
        ]
        for f in files
    }


class TestMultiFile:
    def test_each_file_keeps_its_own_hunk(self):
        assert summary(parse(TWO_FILES)) == {
            "a.py": [(1, ["old_a"], ["new_a"])],
            "b.py": [(10, ["old_b"], ["new_b"])],
        }

    def test_three_files_with_several_hunks(self):
        third = TWO_FILES.replace("a.py", "c.py").replace("b.py", "d.py")
        second_hunk = "@@ -50,2 +50,2 @@\n-x\n+y\n z\n"
        text = TWO_FILES.replace(
            "diff --git a/b.py", second_hunk + "diff --git a/b.py", 1
        )
        text += third
        result = summary(parse(text))
        assert list(result) == ["a.py", "b.py", "c.py", "d.py"]
        assert [h[0] for h in result["a.py"]] == [1, 50]
        assert [h[0] for h in result["b.py"]] == [10]
        assert [h[0] for h in result["c.py"]] == [1]
        assert [h[0] for h in result["d.py"]] == [10]

    def test_file_without_hunks_gets_none(self):
        text = (
            "diff --git a/a.py b/a.py\nnew file mode 100644\n"
            "diff --git a/b.py b/b.py\nindex 1..2 100644\n"
            "--- a/b.py\n+++ b/b.py\n@@ -1,1 +1,1 @@\n-x\n+y\n"
        )
        result = summary(parse(text))
        assert result["a.py"] == []
        assert result["b.py"] == [(1, ["x"], ["y"])]


class TestContentLooksLikeHeaders:
    def test_removed_and_added_lines_starting_with_dashes_and_pluses(self):
        text = (
            "diff --git a/c.yml b/c.yml\n"
            "--- a/c.yml\n+++ b/c.yml\n"
            "@@ -1,4 +1,4 @@\n"
            " a: 1\n"
            "---\n"  # removed line whose content is "--"
            "+++\n"  # added line whose content is "++"
            " b: 2\n"
            "-c: 3\n"
            "+c: 4\n"
        )
        files = parse(text)
        hunk = files[0]["hunks"][0]
        assert [e["content"] for e in hunk["removed_lines"]] == ["--", "c: 3"]
        assert [e["content"] for e in hunk["added_lines"]] == ["++", "c: 4"]
        # Line numbers must not drift after such lines.
        assert hunk["added_lines"][-1]["line"] == 4
        assert hunk["removed_lines"][-1]["line"] == 4
