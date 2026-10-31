"""Tests for RepoSource (read-only repository access for the agent)."""

import os
import subprocess

import pytest

from diff_parser import RepoAccessError, RepoSource


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    """Temp repo: base commit on main, a feature commit, then staged and
    unstaged edits on top."""
    r = str(tmp_path)
    _git(r, "init", "-q", "-b", "main")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "src" / "util.py").write_text("def helper():\n    return foo()\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    (tmp_path / "server.pem").write_text("KEY\n")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02")
    os.symlink("src/app.py", tmp_path / "link.py")
    _git(r, "add", "-f", ".")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "checkout", "-q", "-b", "feature")
    (tmp_path / "src" / "app.py").write_text("def foo():\n    return 2\n")
    _git(r, "commit", "-qam", "feature")
    # staged change, then a different unstaged change on top
    (tmp_path / "src" / "app.py").write_text("def foo():\n    return 3\n")
    _git(r, "add", "src/app.py")
    (tmp_path / "src" / "app.py").write_text("def foo():\n    return 4\n")
    return r


class TestRead:
    def test_modes_see_their_own_content(self, repo):
        assert "return 4" in RepoSource(repo, "worktree").read("src/app.py")
        assert "return 3" in RepoSource(repo, "index").read("src/app.py")
        assert "return 2" in RepoSource(repo, "rev", rev="feature").read("src/app.py")
        assert "return 1" in RepoSource(repo, "rev", rev="main").read("src/app.py")

    def test_untouched_file_same_in_all_modes(self, repo):
        expected = "def helper():\n    return foo()\n"
        for src in (
            RepoSource(repo, "worktree"),
            RepoSource(repo, "index"),
            RepoSource(repo, "rev", rev="feature"),
        ):
            assert src.read("src/util.py") == expected

    def test_line_range(self, repo):
        src = RepoSource(repo, "worktree")
        assert src.read("src/app.py", start=2, end=2) == "    return 4"

    def test_truncation(self, repo):
        text = RepoSource(repo, "worktree").read("src/app.py", max_bytes=5)
        assert text.endswith("[truncated]")

    def test_missing_file(self, repo):
        for mode in ("worktree", "index"):
            with pytest.raises(FileNotFoundError):
                RepoSource(repo, mode).read("nope.py")
        with pytest.raises(FileNotFoundError):
            RepoSource(repo, "rev", rev="main").read("nope.py")

    def test_binary_rejected(self, repo):
        for src in (RepoSource(repo, "worktree"), RepoSource(repo, "index")):
            with pytest.raises(RepoAccessError):
                src.read("bin.dat")


class TestPathSafety:
    @pytest.mark.parametrize(
        "bad",
        [
            "../etc/passwd",
            "src/../../x",
            "/etc/passwd",
            "C:\\x",
            ".git/config",
            "a\x00b",
        ],
    )
    def test_escape_rejected(self, repo, bad):
        for mode in ("worktree", "index"):
            with pytest.raises(RepoAccessError):
                RepoSource(repo, mode).read(bad)

    def test_symlink_rejected_in_all_modes(self, repo):
        for src in (
            RepoSource(repo, "worktree"),
            RepoSource(repo, "index"),
            RepoSource(repo, "rev", rev="main"),
        ):
            with pytest.raises(RepoAccessError):
                src.read("link.py")

    def test_symlinked_directory_rejected(self, repo, tmp_path_factory):
        outside = tmp_path_factory.mktemp("outside")
        (outside / "x.txt").write_text("outside")
        os.symlink(outside, os.path.join(repo, "evil"))
        with pytest.raises(RepoAccessError):
            RepoSource(repo, "worktree").read("evil/x.txt")

    @pytest.mark.parametrize("denied", [".env", "server.pem"])
    def test_deny_list(self, repo, denied):
        for src in (
            RepoSource(repo, "worktree"),
            RepoSource(repo, "index"),
            RepoSource(repo, "rev", rev="main"),
        ):
            with pytest.raises(RepoAccessError):
                src.read(denied)

    def test_rev_option_injection(self, repo):
        with pytest.raises(ValueError):
            RepoSource(repo, "rev", rev="--output=x")


class TestListAndFind:
    def test_list_root_and_dir(self, repo):
        src = RepoSource(repo, "worktree")
        root = src.list_dir("")
        assert "src/" in root and "bin.dat" in root
        assert ".env" not in root and "server.pem" not in root
        assert src.list_dir("src") == ["src/app.py", "src/util.py"]

    def test_list_same_for_index_and_rev(self, repo):
        assert RepoSource(repo, "index").list_dir("src") == [
            "src/app.py",
            "src/util.py",
        ]
        assert RepoSource(repo, "rev", rev="main").list_dir("src") == [
            "src/app.py",
            "src/util.py",
        ]

    def test_list_empty_dir(self, repo):
        assert RepoSource(repo, "worktree").list_dir("nothing") == []

    def test_find_files(self, repo):
        assert RepoSource(repo, "worktree").find_files("*.py") == [
            "link.py",
            "src/app.py",
            "src/util.py",
        ]
        assert RepoSource(repo, "worktree").find_files("*.pem") == []


class TestGrep:
    def test_matches(self, repo):
        res = RepoSource(repo, "worktree").grep(r"foo\(")
        assert {(m["path"], m["line"]) for m in res} == {
            ("src/app.py", 1),
            ("src/util.py", 2),
        }

    def test_modes_differ_by_content(self, repo):
        assert RepoSource(repo, "index").grep("return 3")[0]["path"] == "src/app.py"
        assert RepoSource(repo, "rev", rev="main").grep("return 1")[0]["line"] == 2
        assert RepoSource(repo, "rev", rev="main").grep("return 4") == []

    def test_no_match_is_empty(self, repo):
        assert RepoSource(repo, "worktree").grep("zzz_not_there") == []

    def test_deny_list_filtered(self, repo):
        assert RepoSource(repo, "worktree").grep("SECRET") == []
        assert RepoSource(repo, "rev", rev="main").grep("SECRET") == []

    def test_pattern_starting_with_dash(self, repo):
        assert RepoSource(repo, "worktree").grep("-x-not-there") == []

    def test_path_filter_and_limit(self, repo):
        res = RepoSource(repo, "worktree").grep("return", path="src", max_matches=1)
        assert len(res) == 1

    def test_invalid_regex(self, repo):
        with pytest.raises(RuntimeError):
            RepoSource(repo, "worktree").grep("(unclosed")

    def test_grep_escape_rejected(self, repo):
        with pytest.raises(RepoAccessError):
            RepoSource(repo, "worktree").grep("x", path="../")


class TestForDiffMode:
    def test_mapping(self, repo):
        assert RepoSource.for_diff_mode("staged", root=repo).mode == "index"
        assert RepoSource.for_diff_mode("unstaged", root=repo).mode == "worktree"
        assert RepoSource.for_diff_mode("all", root=repo).mode == "worktree"
        src = RepoSource.for_diff_mode("range", head="feature", root=repo)
        assert (src.mode, src.rev) == ("rev", "feature")
        with pytest.raises(ValueError):
            RepoSource.for_diff_mode("bogus", root=repo)
