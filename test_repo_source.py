"""Tests for RepoSource (read-only repository access for the agent)."""

import os
import subprocess
from pathlib import Path

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


class TestReadLines:
    @pytest.fixture
    def files(self, repo):
        """Add files of several shapes, then stage them."""
        root = Path(repo)
        (root / "five.txt").write_text("l1\nl2\nl3\nl4\nl5\n")
        (root / "nonl.txt").write_text("a\nb")  # No newline at the end.
        (root / "empty.txt").write_text("")
        (root / "crlf.txt").write_bytes(b"a\r\nb\r\n")
        (root / "long.txt").write_text("".join(f"line{i}\n" for i in range(40_000)))
        _git(repo, "add", "five.txt", "nonl.txt", "empty.txt", "crlf.txt", "long.txt")
        _git(repo, "commit", "-qm", "files")
        return repo

    def sources(self, repo):
        return [
            RepoSource(repo, "worktree"),
            RepoSource(repo, "index"),
            RepoSource(repo, "rev", rev="HEAD"),
        ]

    def test_range_is_the_same_in_every_mode(self, files):
        for src in self.sources(files):
            part = src.read_lines("five.txt", 2, 4)
            assert part.lines == ["l2", "l3", "l4"]
            assert (part.first, part.scanned, part.total) == (2, 5, 5)

    def test_range_past_the_end(self, files):
        for src in self.sources(files):
            part = src.read_lines("five.txt", 4, 99)
            assert part.lines == ["l4", "l5"] and part.total == 5
            part = src.read_lines("five.txt", 50, 60)
            assert part.lines == [] and part.total == 5

    def test_last_line_without_newline(self, files):
        for src in self.sources(files):
            part = src.read_lines("nonl.txt", 1, 10)
            assert part.lines == ["a", "b"] and part.total == 2

    def test_empty_file(self, files):
        for src in self.sources(files):
            part = src.read_lines("empty.txt", 1, 10)
            assert part.lines == [] and part.total == 0

    def test_carriage_returns_stay_in_the_text(self, files):
        part = RepoSource(files, "worktree").read_lines("crlf.txt", 1, 2)
        assert part.lines == ["a\r", "b\r"]

    def test_deep_range_in_a_large_file(self, files):
        for src in self.sources(files):
            part = src.read_lines("long.txt", 39_998, 40_000)
            assert part.lines == ["line39997", "line39998", "line39999"]
            assert part.total == 40_000

    def test_invalid_range_values_are_corrected(self, files):
        part = RepoSource(files, "worktree").read_lines("five.txt", 0, -5)
        assert part.lines == ["l1"] and part.first == 1

    def test_scan_limit_makes_the_total_unknown(self, files):
        # The limit applies per 64 KB chunk. long.txt has about 380 KB.
        for src in self.sources(files):
            part = src.read_lines("long.txt", 1, 3, max_scan_bytes=1000)
            assert part.lines == ["line0", "line1", "line2"]
            assert part.total is None
            assert 5000 < part.scanned < 40_000

    def test_lines_after_the_scan_limit_are_not_available(self, files):
        for src in self.sources(files):
            part = src.read_lines("long.txt", 39_000, 39_010, max_scan_bytes=1000)
            assert part.lines == [] and part.total is None

    def test_small_file_is_complete_with_a_tiny_limit(self, files):
        part = RepoSource(files, "worktree").read_lines(
            "five.txt", 1, 5, max_scan_bytes=1
        )
        assert part.total == 5

    @pytest.mark.parametrize("mode", ["worktree", "index"])
    def test_refusals_are_the_same_as_for_read(self, files, mode):
        src = RepoSource(files, mode)
        with pytest.raises(RepoAccessError):
            src.read_lines("bin.dat", 1, 2)
        with pytest.raises(RepoAccessError):
            src.read_lines(".env", 1, 2)
        with pytest.raises(RepoAccessError):
            src.read_lines("link.py", 1, 2)
        with pytest.raises(RepoAccessError):
            src.read_lines("../x", 1, 2)
        with pytest.raises(FileNotFoundError):
            src.read_lines("nope.txt", 1, 2)

    def test_read_stops_at_the_byte_limit_in_every_mode(self, files):
        for src in self.sources(files):
            text = src.read("long.txt")
            assert len(text) == 200_000 + len("\n[truncated]")
            assert text.endswith("\n[truncated]")

    def test_git_process_is_stopped_after_an_early_exit(self, files, monkeypatch):
        started = []
        real = subprocess.Popen

        def spy(*args, **kwargs):
            proc = real(*args, **kwargs)
            started.append(proc)
            return proc

        monkeypatch.setattr(subprocess, "Popen", spy)
        RepoSource(files, "index").read_lines("long.txt", 1, 2, max_scan_bytes=1000)
        assert started and all(p.poll() is not None for p in started)


DENIED_NAMES = [
    "secrets.yml",
    "config/secrets.json",
    "terraform.tfstate",
    "prod.tfvars",
    "local_settings.py",
    "app/settings_local.py",
    "service-account-prod.json",
    "key.p8",
    "release.keystore",
    ".aws/credentials",
    ".ssh/config",
    ".kube/config",
    ".docker/config.json",
    ".pgpass",
    ".git-credentials",
]


class TestMoreDeniedFiles:
    @pytest.fixture
    def secret_repo(self, tmp_path):
        root = tmp_path / "r"
        root.mkdir()
        _git(str(root), "init", "-q", "-b", "main")
        for name in [*DENIED_NAMES, "secrets.py", "app/utils.py", ".dockerignore"]:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("token = 'abcdef0123456789abcdef'\n")
        _git(str(root), "add", "-f", ".")
        _git(str(root), "commit", "-q", "-m", "x")
        return str(root)

    @pytest.mark.parametrize("name", DENIED_NAMES)
    def test_read_is_refused_in_every_mode(self, secret_repo, name):
        for src in (
            RepoSource(secret_repo, "worktree"),
            RepoSource(secret_repo, "index"),
            RepoSource(secret_repo, "rev", rev="HEAD"),
        ):
            with pytest.raises(RepoAccessError):
                src.read(name)
            with pytest.raises(RepoAccessError):
                src.read_lines(name, 1, 2)

    def test_denied_files_do_not_show_in_lists_or_search(self, secret_repo):
        src = RepoSource(secret_repo, "worktree")
        listed = src.find_files("*")
        for name in DENIED_NAMES:
            assert name not in listed
        matches = {m["path"] for m in src.grep("abcdef0123456789")}
        assert matches == {"secrets.py", "app/utils.py", ".dockerignore"}

    def test_normal_code_files_with_similar_names_stay_readable(self, secret_repo):
        src = RepoSource(secret_repo, "worktree")
        for name in ("secrets.py", "app/utils.py", ".dockerignore"):
            assert "token" in src.read(name)


class TestGitTimeout:
    def test_slow_git_command_times_out(self, repo, monkeypatch):
        import subprocess as sp

        source = RepoSource(repo, "worktree", git_timeout=7)

        def slow(*args, **kwargs):
            assert kwargs["timeout"] == 7
            raise sp.TimeoutExpired(args[0], kwargs["timeout"])

        monkeypatch.setattr("diff_parser.subprocess.run", slow)
        with pytest.raises(RuntimeError, match="timed out after 7 seconds"):
            source.grep("x")

    def test_is_denied_is_public(self, repo):
        source = RepoSource(repo, "worktree")
        assert source.is_denied("a/.env") and not source.is_denied("src/app.py")
