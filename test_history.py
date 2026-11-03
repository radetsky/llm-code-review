"""Tests for the history cost tool. They do not call an LLM."""

import json
import subprocess
from pathlib import Path

import pytest

from config import ReviewConfig
from evaluation import history
from evaluation.history import (
    Sample,
    bucket_of,
    diff_size,
    list_commits,
    pick_samples,
    record_of,
    render,
    summarize,
)


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def commit(repo: Path, message: str, **files):
    for name, lines in files.items():
        path = repo / name.replace("__", "/").replace("_py", ".py").replace(
            "_md", ".md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text() if path.exists() else ""
        path.write_text(
            existing + "".join(f"line {message} {i}\n" for i in range(lines))
        )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    commit(root, "root", a_py=2)
    commit(root, "tiny", a_py=5)  # 5 lines: small
    commit(root, "docs only", notes_md=500)  # A file type that the review skips
    commit(root, "mid", b_py=60)  # medium
    commit(root, "big", c_py=300)  # large
    commit(root, "huge", d_py=900)  # huge
    return root


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return ReviewConfig()


class TestBuckets:
    @pytest.mark.parametrize(
        "lines,expected",
        [
            (0, None),
            (1, "small"),
            (40, "small"),
            (41, "medium"),
            (200, "medium"),
            (201, "large"),
            (800, "large"),
            (801, "huge"),
            (50000, "huge"),
        ],
    )
    def test_boundaries(self, lines, expected):
        assert bucket_of(lines) == expected


class TestDiffSize:
    def test_counts_only_files_that_the_review_reads(self, repo, config):
        head = list_commits(repo, 10)
        docs = next(c for c in head if "docs only" in subject(repo, c))
        assert diff_size(repo, f"{docs}^", docs, config) == (0, 0)

    def test_counts_added_and_removed_lines(self, repo, config):
        sha = next(c for c in list_commits(repo, 10) if subject(repo, c) == "mid")
        assert diff_size(repo, f"{sha}^", sha, config) == (1, 60)
        (repo / "b.py").write_text("one line\n")
        git(repo, "commit", "-qam", "shrink")
        sha = list_commits(repo, 1)[0]
        assert diff_size(repo, f"{sha}^", sha, config) == (1, 61)  # 1 added, 60 removed

    def test_binary_files_are_skipped(self, repo, config):
        (repo / "x.py").write_bytes(b"\x00\x01\x02" * 100)
        git(repo, "add", "x.py")
        git(repo, "commit", "-qm", "binary")
        sha = list_commits(repo, 1)[0]
        assert diff_size(repo, f"{sha}^", sha, config)[0] <= 1


def subject(repo, sha):
    return subprocess.run(
        ["git", "log", "-1", "--format=%s", sha],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class TestListCommits:
    def test_newest_first_and_the_root_is_left_out(self, repo):
        subjects = [subject(repo, c) for c in list_commits(repo, 50)]
        assert subjects == ["huge", "big", "mid", "docs only", "tiny"]

    def test_limit(self, repo):
        assert len(list_commits(repo, 2)) == 2

    def test_merges_are_skipped(self, repo):
        git(repo, "checkout", "-q", "-b", "side", "HEAD~2")
        commit(repo, "side work", s_py=3)
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "-q", "--no-ff", "side", "-m", "merge side")
        subjects = [subject(repo, c) for c in list_commits(repo, 50)]
        assert "merge side" not in subjects and "side work" in subjects


class TestPickSamples:
    def test_one_commit_for_each_class(self, repo, config):
        samples = pick_samples(
            repo, list_commits(repo, 50), per_bucket=1, config=config
        )
        by_bucket = {s.bucket: s for s in samples}
        assert by_bucket["small"].label == "tiny" and by_bucket["small"].lines == 5
        assert by_bucket["medium"].label == "mid"
        assert by_bucket["large"].label == "big"
        assert by_bucket["huge"].label == "huge"
        assert all(s.commits == 1 and s.base == f"{s.head}^" for s in samples)

    def test_order_is_by_class(self, repo, config):
        samples = pick_samples(repo, list_commits(repo, 50), 1, config)
        assert [s.bucket for s in samples] == ["small", "medium", "large", "huge"]

    def test_commits_that_the_review_skips_are_not_samples(self, repo, config):
        samples = pick_samples(repo, list_commits(repo, 50), 5, config)
        assert "docs only" not in [s.label for s in samples]

    def test_a_window_fills_a_class_that_single_commits_do_not(self, tmp_path, config):
        root = tmp_path / "w"
        root.mkdir()
        git(root, "init", "-q", "-b", "main")
        commit(root, "root", a_py=1)
        for i in range(8):  # Each commit is small. Together they are large.
            commit(root, f"part {i}", **{f"f{i}_py": 35})
        samples = pick_samples(root, list_commits(root, 50), 1, config)
        large = [s for s in samples if s.bucket == "large"]
        assert large and large[0].commits >= 6 and large[0].lines > 200
        assert large[0].label.endswith("commits")

    def test_no_duplicates_and_the_limit_holds(self, repo, config):
        samples = pick_samples(repo, list_commits(repo, 50), 2, config)
        keys = [(s.base, s.head) for s in samples]
        assert len(keys) == len(set(keys))
        for bucket in ("small", "medium", "large", "huge"):
            assert sum(1 for s in samples if s.bucket == bucket) <= 2


SAMPLE = Sample("large", "aaa^", "aaa", 1, 5, 300, "a change")


def good(engine="agent", **kw):
    result = {
        "status": "success",
        "engine": engine,
        "critical_issues": ["a.py:1: c"],
        "warnings": ["a.py:2: w", "a.py:3: w2"],
        "suggestions": ["a.py:4: s"],
        "code_suggestions": [{"file": "a.py"}],
        "redacted_count": 1,
        "duration_sec": 12.5,
        "agent_stats": {
            "steps": 4,
            "tokens": 9000,
            "tool_calls": 6,
            "invalid_tool_calls": 1,
            "forced_submit": None,
            "fallback": None,
        },
    }
    result.update(kw)
    return result


class TestRecord:
    def test_agent_record(self):
        r = record_of(SAMPLE, "agent", good(), 3000)
        assert r["ok"] and (r["critical"], r["warnings"], r["suggestions"]) == (1, 2, 2)
        assert (r["steps"], r["tokens"], r["redacted"], r["classic_prompt_tokens"]) == (
            4,
            9000,
            1,
            3000,
        )
        assert [f["severity"] for f in r["findings"]] == [
            "critical",
            "warning",
            "warning",
            "suggestion",
        ]

    def test_classic_record_has_no_agent_figures(self):
        r = record_of(SAMPLE, "classic", good("classic", agent_stats=None), 3000)
        assert r["ok"] and r["steps"] is None and r["tokens"] is None

    @pytest.mark.parametrize(
        "result",
        [{"error": "timeout", "duration_sec": 9}, {"status": "model_unavailable"}],
    )
    def test_failed_record(self, result):
        r = record_of(SAMPLE, "agent", result, 1)
        assert not r["ok"] and r["error"]


class TestSummarize:
    def records(self):
        return [
            record_of(SAMPLE, "agent", good(), 3000),
            record_of(
                SAMPLE,
                "agent",
                good(
                    agent_stats={
                        "steps": 20,
                        "tokens": 90000,
                        "tool_calls": 30,
                        "invalid_tool_calls": 0,
                        "forced_submit": "max_steps",
                        "fallback": "classic",
                    },
                    duration_sec=60,
                ),
                3000,
            ),
            record_of(SAMPLE, "agent", {"error": "boom"}, 3000),
        ]

    def test_numbers(self):
        s = summarize(self.records())
        assert (s["runs"], s["failed"]) == (3, 1)
        assert s["total_tokens"] == 99000 and s["forced"] == 1 and s["fallback"] == 1
        assert s["tool_calls"] == 36 and s["invalid_calls"] == 1
        assert s["median_steps"] == 4 and s["p90_tokens"] == 90000
        assert s["findings_per_run"] == 3.0

    def test_empty(self):
        s = summarize([])
        assert (
            s["runs"] == 0
            and s["median_time"] is None
            and s["findings_per_run"] is None
        )


class TestRender:
    def test_tables(self):
        small = Sample("small", "b^", "b", 1, 1, 10, "tiny change")
        records = [
            record_of(SAMPLE, "classic", good("classic", agent_stats=None), 3000),
            record_of(SAMPLE, "agent", good(), 3000),
            record_of(small, "classic", {"error": "timeout after 5 s"}, 100),
            record_of(
                small,
                "agent",
                good(
                    agent_stats={"steps": 20, "tokens": 5, "forced_submit": "max_steps"}
                ),
                100,
            ),
        ]
        text = render(records, {"date": "d", "model": "m"})
        assert (
            "## Summary for each size class" in text and "| large | classic |" in text
        )
        assert "| large | agent | 1 (0) |" in text
        assert "| small | classic | 1 (1) |" in text
        assert "FAILED: timeout after 5 s" in text and "(budget)" in text
        assert "`aaa` a change" in text and "Model: m" in text
        assert "Tokens in total: 9005" in text

    def test_one_engine(self):
        text = render([record_of(SAMPLE, "agent", good(), 1)], {})
        assert "engines: agent" in text and "classic: time" not in text


class FakeRunner:
    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer or (
            lambda engine: good(
                engine,
                agent_stats=None if engine == "classic" else good()["agent_stats"],
            )
        )

    def __call__(self, engine, repo, config_file, timeout, base=None, head=None):
        self.calls.append((engine, base, head, Path(config_file)))
        return self.answer(engine)


class TestMain:
    def run(self, repo, tmp_path, *argv, runner=None):
        runner = runner or FakeRunner()
        code = history.main(
            ["--repo", str(repo), "--out", str(tmp_path / "out"), *argv], runner=runner
        )
        return code, runner

    def test_list_runs_nothing(self, repo, tmp_path, capsys):
        code, runner = self.run(repo, tmp_path, "--list", "--per-bucket", "1")
        assert code == 0 and runner.calls == []
        assert "small" in capsys.readouterr().out

    def test_full_run_writes_files(self, repo, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(history, "classic_prompt_tokens", lambda *a: 1234)
        code, runner = self.run(repo, tmp_path, "--per-bucket", "1")
        assert code == 0 and len(runner.calls) == 4 * 2
        assert {c[0] for c in runner.calls} == {"classic", "agent"}
        assert all(c[1] and c[2] for c in runner.calls)  # Base and head are given.
        out = tmp_path / "out"
        assert (out / "report.md").read_text().startswith("# Cost on real changes")
        data = json.loads((out / "runs.json").read_text())
        assert (
            len(data["runs"]) == 8 and data["runs"][0]["classic_prompt_tokens"] == 1234
        )

    def test_the_config_turns_the_log_on(self, repo, tmp_path, monkeypatch):
        monkeypatch.setattr(history, "classic_prompt_tokens", lambda *a: 1)
        _, runner = self.run(repo, tmp_path, "--per-bucket", "1", "--engines", "agent")
        config = json.loads(runner.calls[0][3].read_text())
        assert config["monitoring"] == {
            "enabled": True,
            "log_dir": str(tmp_path / "out" / "logs"),
        }
        assert config["llm"]  # The rest of the config stays.

    def test_failures_do_not_stop_the_run(self, repo, tmp_path, monkeypatch):
        monkeypatch.setattr(history, "classic_prompt_tokens", lambda *a: 1)
        runner = FakeRunner(lambda engine: {"error": "timeout", "duration_sec": 1})
        code, runner = self.run(
            repo, tmp_path, "--per-bucket", "1", "--engines", "agent", runner=runner
        )
        assert code == 0 and len(runner.calls) == 4
        assert "FAILED: timeout" in (tmp_path / "out" / "report.md").read_text()

    @pytest.mark.parametrize("argv", [["--engines", "turbo"], ["--per-bucket", "0"]])
    def test_bad_arguments(self, repo, tmp_path, argv):
        with pytest.raises(SystemExit) as error:
            self.run(repo, tmp_path, *argv)
        assert error.value.code == 2

    def test_missing_config(self, repo, tmp_path, capsys):
        code, _ = self.run(repo, tmp_path, "--config", str(tmp_path / "none.json"))
        assert code == 4 and "config file not found" in capsys.readouterr().err

    def test_a_repository_without_reviewable_changes(self, tmp_path, capsys):
        root = tmp_path / "empty"
        root.mkdir()
        git(root, "init", "-q", "-b", "main")
        commit(root, "root", notes_md=1)
        commit(root, "more", notes_md=1)
        code, _ = self.run(root, tmp_path)
        assert code == 4 and "No change of a supported size" in capsys.readouterr().err
