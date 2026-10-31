"""Tests for the read-only agent tools."""

import subprocess

import pytest

from agent_tools import TOOL_SPECS, AgentTools
from config import ReviewConfig
from diff_parser import DiffParser, RepoSource


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=Tester", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Repo with one base commit and a staged change to app.py."""
    r = str(tmp_path)
    _git(r, "init", "-q", "-b", "main")
    (tmp_path / "app.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "util.py").write_text("class Helper:\n    pass\n\nMAX = 1\n")
    (tmp_path / "svc.go").write_text("package x\n\nfunc (s *S) Run() {}\n")
    (tmp_path / "big.py").write_text("".join(f"x{i} = {i}\n" for i in range(5000)))
    (tmp_path / ".env").write_text("SECRET=1\n")
    _git(r, "add", "-f", ".")
    _git(r, "commit", "-q", "-m", "initial commit")
    (tmp_path / "app.py").write_text(
        "def foo():\n    return 2\n\n\ndef bar():\n    return foo()\n"
    )
    _git(r, "add", "app.py")
    monkeypatch.chdir(tmp_path)
    return r


@pytest.fixture
def tools(repo):
    config = ReviewConfig()
    parser = DiffParser(config)
    parsed = parser.parse_diff(parser.get_diff("staged"))
    return AgentTools(config, RepoSource(repo, "index"), parser, parsed)


class TestSpecs:
    def test_every_spec_has_a_handler(self, tools):
        names = {s["function"]["name"] for s in TOOL_SPECS}
        assert names == set(tools._handlers)
        assert len(names) == 8

    def test_required_fields_exist_in_properties(self):
        for spec in TOOL_SPECS:
            params = spec["function"]["parameters"]
            assert set(params["required"]) <= set(params["properties"])


class TestDispatch:
    def test_unknown_tool(self, tools):
        out = tools.call("rm_rf", {})
        assert out.startswith("Error: unknown tool 'rm_rf'")
        assert "read_file" in out

    def test_arguments_not_object(self, tools):
        assert tools.call("read_file", "app.py").startswith("Error:")
        assert tools.call("read_file", ["app.py"]).startswith("Error:")

    def test_none_arguments_treated_as_empty(self, tools):
        assert "app.py" in tools.call("list_changed_files", None)

    def test_missing_required_argument(self, tools):
        assert "missing required argument 'path'" in tools.call("read_file", {})

    def test_wrong_argument_type(self, tools):
        assert "must be a string" in tools.call("read_file", {"path": 5})
        assert "must be an integer" in tools.call(
            "read_file", {"path": "app.py", "start_line": "abc"}
        )
        assert "must be an integer" in tools.call(
            "read_file", {"path": "app.py", "start_line": True}
        )


class TestChangedFilesAndDiff:
    def test_list_changed_files(self, tools):
        assert tools.call("list_changed_files", {}) == "app.py (modified) +5 -1"

    def test_list_changed_files_empty(self, repo):
        config = ReviewConfig()
        t = AgentTools(config, RepoSource(repo, "index"), DiffParser(config), [])
        assert t.call("list_changed_files", {}) == "No changed files."

    def test_get_diff_numbered(self, tools):
        out = tools.call("get_diff", {"path": "app.py"})
        assert "File: app.py (modified)" in out
        assert "- 2:     return 1" in out
        assert "+ 2:     return 2" in out

    def test_get_diff_unchanged_file(self, tools):
        out = tools.call("get_diff", {"path": "util.py"})
        assert "not in the changed files list" in out


class TestReadFile:
    def test_numbers_lines(self, tools):
        out = tools.call("read_file", {"path": "util.py"})
        assert out.startswith("1: class Helper:\n2:     pass")

    def test_reads_staged_content(self, tools):
        assert "2:     return 2" in tools.call("read_file", {"path": "app.py"})

    def test_range_keeps_original_numbers(self, tools):
        out = tools.call(
            "read_file", {"path": "app.py", "start_line": 5, "end_line": 6}
        )
        assert out == "5: def bar():\n6:     return foo()"

    def test_invalid_range(self, tools):
        assert "start_line must be >= 1" in tools.call(
            "read_file", {"path": "app.py", "start_line": 0}
        )
        assert "end_line must be >= start_line" in tools.call(
            "read_file", {"path": "app.py", "start_line": 4, "end_line": 2}
        )

    def test_range_past_eof_is_empty(self, tools):
        out = tools.call(
            "read_file", {"path": "app.py", "start_line": 99, "end_line": 100}
        )
        assert out == "(empty)"

    def test_missing_file(self, tools):
        assert tools.call("read_file", {"path": "nope.py"}) == "Error: file not found"

    def test_denied_and_escaping_paths(self, tools):
        assert tools.call("read_file", {"path": ".env"}).startswith("Error:")
        assert tools.call("read_file", {"path": "../x"}).startswith("Error:")
        assert tools.call("read_file", {"path": "/etc/passwd"}).startswith("Error:")

    def test_large_file_is_truncated(self, tools):
        out = tools.call("read_file", {"path": "big.py"})
        assert "[output truncated" in out
        assert len(out) < tools.max_chars + 200

    def test_truncation_limit_from_config(self, tools):
        tools.config.config["agent"] = {"max_tool_output_chars": 50}
        out = tools.call("read_file", {"path": "big.py"})
        assert out.startswith("1: x0 = 0")
        assert len(out) < 200


class TestSearch:
    def test_grep(self, tools):
        out = tools.call("grep", {"pattern": "class Helper"})
        assert out == "util.py:1: class Helper:"

    def test_grep_path_filter(self, tools):
        out = tools.call("grep", {"pattern": "foo", "path": "app.py"})
        assert "app.py:1:" in out and "util.py" not in out

    def test_grep_no_match(self, tools):
        assert tools.call("grep", {"pattern": "zzz_nothing"}) == "No matches."

    def test_grep_invalid_regex(self, tools):
        assert tools.call("grep", {"pattern": "(unclosed"}).startswith("Error:")

    def test_grep_does_not_leak_denied_files(self, tools):
        assert tools.call("grep", {"pattern": "SECRET"}) == "No matches."

    def test_grep_match_limit(self, tools):
        tools.config.config["agent"] = {"max_grep_matches": 3}
        out = tools.call("grep", {"pattern": "^x[0-9]+ = "})
        assert len(out.split("\n")) == 3

    def test_find_files(self, tools):
        assert tools.call("find_files", {"pattern": "*.go"}) == "svc.go"

    def test_find_files_empty(self, tools):
        assert tools.call("find_files", {"pattern": "*.rs"}) == "No files found."

    def test_find_files_hides_denied(self, tools):
        assert tools.call("find_files", {"pattern": ".env"}) == "No files found."


class TestFindDefinition:
    def test_python_function_uses_staged_content(self, tools):
        assert tools.call("find_definition", {"name": "bar"}) == "app.py:5: def bar():"

    def test_class(self, tools):
        assert tools.call("find_definition", {"name": "Helper"}) == (
            "util.py:1: class Helper:"
        )

    def test_go_method(self, tools):
        out = tools.call("find_definition", {"name": "Run"})
        assert out == "svc.go:3: func (s *S) Run() {}"

    def test_not_found(self, tools):
        out = tools.call("find_definition", {"name": "Nothing"})
        assert out.startswith("No definition of 'Nothing' found")

    def test_name_must_be_identifier(self, tools):
        for bad in ("a.*", "foo(", "a b", "-e", "x|y"):
            assert "plain identifier" in tools.call("find_definition", {"name": bad})

    def test_partial_names_do_not_match(self, tools):
        assert tools.call("find_definition", {"name": "fo"}).startswith("No definition")


class TestHistory:
    def test_git_log(self, tools):
        out = tools.call("git_log", {})
        assert out.endswith("Tester: initial commit")

    def test_git_log_path_and_count(self, tools):
        assert "initial commit" in tools.call(
            "git_log", {"path": "app.py", "max_count": 1}
        )

    def test_git_log_path_without_history(self, tools):
        assert tools.call("git_log", {"path": "missing.py"}) == "No commits found."

    def test_git_log_denied_path(self, tools):
        assert tools.call("git_log", {"path": ".env"}).startswith("Error:")

    def test_git_blame(self, tools):
        out = tools.call(
            "git_blame", {"path": "util.py", "start_line": 1, "end_line": 2}
        )
        assert out.count("Tester") == 2
        assert "class Helper:" in out

    def test_git_blame_requires_range(self, tools):
        assert "required" in tools.call("git_blame", {"path": "util.py"})

    def test_git_blame_bad_range(self, tools):
        out = tools.call(
            "git_blame", {"path": "util.py", "start_line": 5, "end_line": 2}
        )
        assert out.startswith("Error:")

    def test_git_blame_range_is_capped(self, tools):
        out = tools.call(
            "git_blame", {"path": "big.py", "start_line": 1, "end_line": 5000}
        )
        assert out.count("Tester") <= 200 or "[output truncated" in out

    def test_git_blame_missing_file(self, tools):
        out = tools.call(
            "git_blame", {"path": "nope.py", "start_line": 1, "end_line": 2}
        )
        assert out == "Error: file not found"
