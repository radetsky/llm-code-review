"""Tests for CLI wiring: engine choice, --fail-on, degradation, hooks."""

import json
import os
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

import review
from config import ReviewConfig
from review import ReviewCLI
from review_core import CodeSuggestion, ReviewResult

ROOT = Path(__file__).parent


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Repo with a base commit, a feature commit and a staged edit."""
    r = str(tmp_path)
    _git(r, "init", "-q", "-b", "main")
    (tmp_path / "app.py").write_text("def foo():\n    return 1\n")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "checkout", "-q", "-b", "feature")
    (tmp_path / "app.py").write_text("def foo():\n    return 2\n")
    _git(r, "commit", "-qam", "feature")
    (tmp_path / "app.py").write_text("def foo():\n    return 3\n")
    _git(r, "add", "app.py")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.invalid/v1")
    monkeypatch.delenv("LLM_ENGINE", raising=False)
    return r


def result(status="success", critical=(), warnings=(), raw=None, stats=None):
    return ReviewResult(
        status=status,
        critical_issues=list(critical),
        warnings=list(warnings),
        suggestions=[],
        raw_response=raw,
        agent_stats=stats,
    )


class FakeAgent:
    """Replaces AgentReviewer; records construction and the tools it gets."""

    outcome = result()
    instances: ClassVar[list] = []

    def __init__(self, config, client=None, trace=False, trace_llm=False):
        self.trace, self.trace_llm = trace, trace_llm
        self.tools = None
        FakeAgent.instances.append(self)

    def review(self, tools):
        self.tools = tools
        return FakeAgent.outcome


@pytest.fixture
def fake_agent(monkeypatch):
    FakeAgent.instances = []
    FakeAgent.outcome = result(stats={"steps": 3, "tool_calls": 2, "tokens": 900})
    monkeypatch.setattr(review, "AgentReviewer", FakeAgent)
    return FakeAgent


def run_cli(*argv):
    return ReviewCLI().run(list(argv))


def run_json(capsys, *argv):
    cli = ReviewCLI()
    code = cli.run([*argv, "--format", "json"])
    out = capsys.readouterr()
    return code, json.loads(out.out), out.err, cli


# -- engine resolution -----------------------------------------------------


class TestEngineResolution:
    def test_default_is_classic(self, monkeypatch):
        monkeypatch.delenv("LLM_ENGINE", raising=False)
        assert ReviewConfig().get_engine() == "classic"

    def test_config_enables_agent(self, monkeypatch):
        monkeypatch.delenv("LLM_ENGINE", raising=False)
        config = ReviewConfig()
        config.config["agent"] = dict(config.config["agent"], enabled=True)
        assert config.get_engine() == "agent"

    def test_precedence_cli_env_config(self, monkeypatch):
        config = ReviewConfig()
        config.config["agent"] = dict(config.config["agent"], enabled=True)
        monkeypatch.setenv("LLM_ENGINE", "classic")
        assert config.get_engine() == "classic"  # env beats config
        assert config.get_engine("agent") == "agent"  # cli beats env

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("LLM_ENGINE", " Agent ")
        assert ReviewConfig().get_engine() == "agent"

    def test_invalid_value(self, monkeypatch):
        monkeypatch.setenv("LLM_ENGINE", "turbo")
        with pytest.raises(ValueError, match="Unsupported engine"):
            ReviewConfig().get_engine()

    def test_invalid_env_is_config_error(self, repo, monkeypatch, capsys):
        monkeypatch.setenv("LLM_ENGINE", "turbo")
        assert run_cli("--mode", "staged") == 4
        assert "Unsupported engine" in capsys.readouterr().err


# -- exit codes ------------------------------------------------------------


class TestExitCodes:
    def code(self, res, fail_on):
        return ReviewCLI()._get_exit_code(res, SimpleNamespace(fail_on=fail_on))

    @pytest.mark.parametrize(
        "res,none,critical,warnings",
        [
            (result(), 0, 0, 0),
            (result(warnings=["w"]), 0, 2, 1),
            (result(critical=["c"]), 0, 1, 1),
            (result(critical=["c"], warnings=["w"]), 0, 1, 1),
            (result(status="model_unavailable"), 0, 3, 3),
            (result(status="skipped"), 0, 5, 5),
        ],
    )
    def test_matrix(self, res, none, critical, warnings):
        assert self.code(res, "none") == none
        assert self.code(res, "critical") == critical
        assert self.code(res, "warnings") == warnings

    def test_missing_args_means_advisory(self):
        assert ReviewCLI()._get_exit_code(result(critical=["c"])) == 0


class TestFailOnFlags:
    def test_default_never_blocks(self, repo, fake_agent):
        fake_agent.outcome = result(critical=["app.py:2: bad"])
        assert run_cli("--engine", "agent", "--mode", "staged") == 0

    def test_fail_on_critical(self, repo, fake_agent):
        fake_agent.outcome = result(critical=["app.py:2: bad"])
        code = run_cli("--engine", "agent", "--fail-on", "critical", "--mode", "staged")
        assert code == 1

    def test_fail_on_critical_allows_warnings(self, repo, fake_agent):
        fake_agent.outcome = result(warnings=["app.py:2: meh"])
        code = run_cli("--engine", "agent", "--fail-on", "critical", "--mode", "staged")
        assert code == 2

    def test_strict_is_alias_of_warnings(self, repo, fake_agent):
        fake_agent.outcome = result(warnings=["app.py:2: meh"])
        assert run_cli("--engine", "agent", "--strict", "--mode", "staged") == 1

    def test_strict_with_same_fail_on_is_fine(self, repo, fake_agent):
        fake_agent.outcome = result(warnings=["app.py:2: meh"])
        code = run_cli("--engine", "agent", "--strict", "--fail-on", "warnings")
        assert code == 1

    def test_strict_conflicting_with_fail_on(self, repo, fake_agent, capsys):
        assert run_cli("--strict", "--fail-on", "none") == 2
        assert "conflicts" in capsys.readouterr().err

    def test_json_exit_code_matches_policy(self, repo, fake_agent, capsys):
        fake_agent.outcome = result(critical=["app.py:2: bad"])
        code, data, _, _ = run_json(
            capsys, "--engine", "agent", "--fail-on", "critical"
        )
        assert code == data["exit_code"] == 1


# -- agent engine wiring ---------------------------------------------------


class TestAgentEngine:
    def test_classic_remains_default(self, repo, monkeypatch, capsys):
        calls = []
        monkeypatch.setattr(
            ReviewCLI,
            "_run_agent_review",
            lambda *a, **k: pytest.fail("agent must not run"),
        )
        monkeypatch.setattr(
            "review_core.LLMReviewer.review_diff",
            lambda self, diff: calls.append(diff) or result(),
        )
        code, data, _, _ = run_json(capsys, "--mode", "staged")
        assert code == 0 and len(calls) == 1
        assert data["engine"] == "classic" and data["agent_stats"] is None

    def test_agent_result_is_reported(self, repo, fake_agent, capsys):
        fake_agent.outcome = result(
            warnings=["app.py:2: meh"], stats={"steps": 3, "tokens": 900}
        )
        code, data, _, _ = run_json(capsys, "--engine", "agent", "--mode", "staged")
        assert code == 0
        assert data["engine"] == "agent"
        assert data["warnings"] == ["app.py:2: meh"]
        assert data["agent_stats"]["steps"] == 3

    def test_env_selects_agent(self, repo, fake_agent, monkeypatch, capsys):
        monkeypatch.setenv("LLM_ENGINE", "agent")
        _, data, _, _ = run_json(capsys, "--mode", "staged")
        assert data["engine"] == "agent" and len(fake_agent.instances) == 1

    @pytest.mark.parametrize(
        "argv,mode,rev",
        [
            (["--mode", "staged"], "index", None),
            ([], "index", None),
            (["--mode", "unstaged"], "worktree", None),
            (["--mode", "all"], "worktree", None),
            (["--base", "main", "--head", "feature"], "rev", "feature"),
        ],
    )
    def test_source_matches_diff_mode(self, repo, fake_agent, argv, mode, rev):
        # An unstaged edit on top of the staged one, so every mode has a diff.
        Path(repo, "app.py").write_text("def foo():\n    return 4\n")
        run_cli("--engine", "agent", *argv)
        tools = fake_agent.instances[0].tools
        assert (tools.source.mode, tools.source.rev) == (mode, rev)

    def test_tools_get_the_parsed_diff(self, repo, fake_agent):
        run_cli("--engine", "agent", "--mode", "staged")
        tools = fake_agent.instances[0].tools
        assert [f["path"] for f in tools.parsed_files] == ["app.py"]
        assert "app.py (modified)" in tools.call("list_changed_files", {})

    def test_trace_flags_reach_the_agent(self, repo, fake_agent):
        run_cli("--engine", "agent", "--trace", "--trace-llm", "--mode", "staged")
        agent = fake_agent.instances[0]
        assert agent.trace is True and agent.trace_llm is True

    def test_trace_off_by_default(self, repo, fake_agent):
        run_cli("--engine", "agent", "--mode", "staged")
        agent = fake_agent.instances[0]
        assert agent.trace is False and agent.trace_llm is False

    def test_no_changes_skips_the_agent(self, repo, fake_agent, capsys):
        _git(repo, "reset", "-q", "--hard", "HEAD")
        code, data, _, _ = run_json(capsys, "--engine", "agent", "--mode", "staged")
        assert code == 0 and fake_agent.instances == []
        assert data["review_outcome"] == "success"

    def test_verbose_shows_engine_and_stats(self, repo, fake_agent, capsys):
        fake_agent.outcome = result(
            stats={"steps": 3, "tool_calls": 2, "tokens": 900, "duration_sec": 4.2}
        )
        run_cli("--engine", "agent", "--mode", "staged", "--verbose")
        out = capsys.readouterr().out
        assert "Engine: agent" in out
        assert "3 step(s), 2 tool call(s), 900 tokens, 4.2s" in out


class TestDegradation:
    @pytest.fixture
    def classic_calls(self, monkeypatch):
        calls = []

        def fake_review(self, diff):
            calls.append(diff)
            return result(warnings=["classic finding"])

        monkeypatch.setattr("review_core.LLMReviewer.review_diff", fake_review)
        return calls

    @pytest.mark.parametrize("status", ["error", "model_unavailable"])
    def test_agent_failure_falls_back_to_classic(
        self, repo, fake_agent, classic_calls, capsys, status
    ):
        fake_agent.outcome = result(
            status=status, raw="boom", stats={"steps": 2, "stop_reason": "x"}
        )
        code, data, err, _ = run_json(capsys, "--engine", "agent", "--mode", "staged")
        assert code == 0
        assert data["engine"] == "agent->classic"
        assert data["warnings"] == ["classic finding"]
        assert data["agent_stats"]["fallback"] == "classic"
        assert data["agent_stats"]["fallback_reason"] == "boom"
        assert data["agent_stats"]["steps"] == 2
        assert f"Agent review failed ({status}): boom" in err
        assert len(classic_calls) == 1
        assert "app.py" in classic_calls[0]  # classic gets the formatted diff

    def test_classic_not_called_when_agent_succeeds(
        self, repo, fake_agent, classic_calls
    ):
        run_cli("--engine", "agent", "--mode", "staged")
        assert classic_calls == []

    def test_full_chain_ends_in_static_and_exit_zero(
        self, repo, fake_agent, monkeypatch, capsys
    ):
        """agent fails, classic model is down too -> static result, exit 0."""
        fake_agent.outcome = result(status="model_unavailable", raw="down")
        monkeypatch.setattr(
            "review_core.LLMReviewer.review_diff",
            lambda self, diff: self._handle_model_unavailable(
                diff, RuntimeError("down")
            ),
        )
        code, data, _, _ = run_json(capsys, "--engine", "agent", "--mode", "staged")
        assert code == 0
        assert data["status"] == "model_unavailable"
        assert data["engine"] == "agent->classic"

    def test_fallback_exit_code_under_fail_on(
        self, repo, fake_agent, monkeypatch, capsys
    ):
        fake_agent.outcome = result(status="error", raw="x")
        monkeypatch.setattr(
            "review_core.LLMReviewer.review_diff",
            lambda self, diff: result(status="model_unavailable"),
        )
        code = run_cli("--engine", "agent", "--fail-on", "critical", "--mode", "staged")
        assert code == 3


# -- hooks -----------------------------------------------------------------


STUB = textwrap.dedent(
    """\
    import sys
    code = int(sys.argv[-1]) if sys.argv[-1].isdigit() else {code}
    print({output!r})
    sys.exit({code})
    """
)


def run_hook(tmp_path, hook, code, output=""):
    (tmp_path / "review.py").write_text(STUB.format(code=code, output=output))
    return subprocess.run(
        ["bash", str(ROOT / "hooks" / hook)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": os.environ["PATH"]},
    )


class TestHooks:
    @pytest.mark.parametrize("hook", ["pre-commit", "pre-push"])
    @pytest.mark.parametrize("code", [0, 1, 2, 3, 4, 5, 7])
    def test_never_blocks(self, tmp_path, hook, code):
        proc = run_hook(tmp_path, hook, code, output="{}")
        assert proc.returncode == 0, proc.stdout + proc.stderr

    @pytest.mark.parametrize("hook", ["pre-commit", "pre-push"])
    def test_missing_review_script(self, tmp_path, hook):
        proc = subprocess.run(
            ["bash", str(ROOT / "hooks" / hook)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0 and "Skipping" in proc.stdout

    def test_pre_commit_reports_config_problem(self, tmp_path):
        proc = run_hook(tmp_path, "pre-commit", 4)
        assert "not configured" in proc.stdout and "commit continues" in proc.stdout

    def test_pre_push_summarizes_findings(self, tmp_path):
        report = json.dumps(
            {
                "critical_issues": ["a.py:1: bad"],
                "warnings": ["a.py:2: meh", "a.py:3: meh2"],
                "suggestions": [],
            }
        )
        proc = run_hook(tmp_path, "pre-push", 0, output=report)
        assert proc.returncode == 0
        assert "Critical: 1, warnings: 2, suggestions: 0" in proc.stdout
        assert "CRITICAL: a.py:1: bad" in proc.stdout

    def test_pre_push_survives_garbage_report(self, tmp_path):
        proc = run_hook(tmp_path, "pre-push", 0, output="not json")
        assert proc.returncode == 0
        assert "Could not read the review report" in proc.stdout


class TestConfigFile:
    def write(self, tmp_path, **review):
        path = tmp_path / "other.json"
        path.write_text(
            json.dumps(
                {
                    "llm": {"model": "other-model"},
                    "output": {"max_context_lines": 3},
                    "review": review,
                }
            )
        )
        return path

    def test_config_file_is_used(self, repo, fake_agent, tmp_path):
        path = self.write(tmp_path, file_extensions=[".py"])
        cli = ReviewCLI()
        cli.run(["--engine", "agent", "--mode", "staged", "--config-file", str(path)])
        assert cli.config.config_file == str(path)
        assert cli.config.get("output.max_context_lines") == 3
        # The parser and the agent use the new config too.
        assert cli.parser.config is cli.config
        assert fake_agent.instances[0].tools.config is cli.config

    def test_default_config_without_the_flag(self, repo, fake_agent):
        cli = ReviewCLI()
        cli.run(["--engine", "agent", "--mode", "staged"])
        assert cli.config.config_file == "review_config.json"

    def test_file_extensions_from_the_file_decide_what_is_reviewed(
        self, repo, fake_agent, tmp_path
    ):
        path = self.write(
            tmp_path, file_extensions=[".rs"]
        )  # The change is a .py file.
        cli = ReviewCLI()
        code = cli.run(
            ["--engine", "agent", "--mode", "staged", "--config-file", str(path)]
        )
        assert code == 0 and fake_agent.instances == []  # Nothing to review.


class TestMonitoringLog:
    def lines(self, repo):
        files = list((Path(repo) / "logs").glob("reviews_*.jsonl"))
        return [json.loads(line) for f in files for line in f.read_text().splitlines()]

    def test_off_by_default(self, repo, fake_agent, monkeypatch):
        monkeypatch.delenv("LLM_MONITORING", raising=False)
        run_cli("--engine", "agent", "--mode", "staged")
        assert not (Path(repo) / "logs").exists()

    def test_agent_review_is_logged(self, repo, fake_agent, monkeypatch):
        monkeypatch.setenv("LLM_MONITORING", "1")
        fake_agent.outcome = result(
            warnings=["app.py:2: meh"],
            stats={"steps": 3, "tokens": 900, "tool_calls": 2},
        )
        run_cli("--engine", "agent", "--mode", "staged")
        (entry,) = self.lines(repo)
        assert entry["metadata"]["engine"] == "agent"
        assert entry["metadata"]["mode"] == "staged"
        assert entry["metadata"]["duration_sec"] >= 0
        assert entry["agent"]["steps"] == 3 and entry["agent"]["tokens"] == 900
        assert entry["result"]["warning_count"] == 1

    def test_classic_review_is_logged(self, repo, monkeypatch):
        monkeypatch.setenv("LLM_MONITORING", "1")
        monkeypatch.setattr(
            "review_core.LLMReviewer.review_diff", lambda self, diff: result()
        )
        run_cli("--mode", "staged")
        (entry,) = self.lines(repo)
        assert entry["metadata"]["engine"] == "classic" and "agent" not in entry

    def test_fallback_is_logged(self, repo, fake_agent, monkeypatch):
        monkeypatch.setenv("LLM_MONITORING", "1")
        fake_agent.outcome = result(
            status="error", raw="boom", stats={"steps": 2, "tokens": 10}
        )
        monkeypatch.setattr(
            "review_core.LLMReviewer.review_diff", lambda self, diff: result()
        )
        run_cli("--engine", "agent", "--base", "main", "--head", "feature")
        (entry,) = self.lines(repo)
        assert entry["metadata"]["engine"] == "agent->classic"
        assert entry["metadata"]["mode"] == "range"
        assert entry["agent"]["fallback"] == "classic"

    def test_a_broken_log_does_not_change_the_review(
        self, repo, fake_agent, monkeypatch, capsys
    ):
        monkeypatch.setenv("LLM_MONITORING", "1")
        (Path(repo) / "logs").write_text("this is a file, not a folder")
        code, data, _, _ = run_json(capsys, "--engine", "agent", "--mode", "staged")
        assert code == 0 and data["status"] == "success"

    def test_log_folder_from_the_config(self, repo, fake_agent, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_MONITORING", "1")
        custom = tmp_path / "elsewhere"
        config = tmp_path / "c.json"
        config.write_text(json.dumps({"monitoring": {"log_dir": str(custom)}}))
        run_cli("--engine", "agent", "--mode", "staged", "--config-file", str(config))
        assert list(custom.glob("reviews_*.jsonl"))
        assert not (Path(repo) / "logs").exists()


SECRET_TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
SECRET_HEX = "4f9c2a7e61b84d3f9a05c8d17e2b6a43"


class TestSecretsAreHidden:
    def leaky(self):
        return ReviewResult(
            status="success",
            critical_issues=[f"app.py:2: hardcoded key {SECRET_TOKEN}"],
            warnings=[f'app.py:3: api_key = "{SECRET_HEX}"'],
            suggestions=[],
            code_suggestions=[
                CodeSuggestion(
                    "app.py", 2, 2, f"remove {SECRET_TOKEN}", f"KEY = '{SECRET_TOKEN}'"
                )
            ],
        )

    def test_json_output(self, repo, fake_agent, capsys):
        fake_agent.outcome = self.leaky()
        code, data, _, _ = run_json(capsys, "--engine", "agent", "--mode", "staged")
        dump = json.dumps(data)
        assert SECRET_TOKEN not in dump and SECRET_HEX not in dump
        assert "[REDACTED]" in data["critical_issues"][0]
        assert data["redacted_count"] == 4 and code == 0

    def test_text_output_has_a_note(self, repo, fake_agent, capsys):
        fake_agent.outcome = self.leaky()
        run_cli("--engine", "agent", "--mode", "staged")
        out = capsys.readouterr().out
        assert SECRET_TOKEN not in out and SECRET_HEX not in out
        assert "4 value(s) that look like secrets are hidden" in out

    def test_no_note_without_secrets(self, repo, fake_agent, capsys):
        run_cli("--engine", "agent", "--mode", "staged")
        assert "secrets are hidden" not in capsys.readouterr().out

    def test_classic_engine_is_covered(self, repo, monkeypatch, capsys):
        leaky = self.leaky()
        monkeypatch.setattr(
            "review_core.LLMReviewer.review_diff", lambda self, diff: leaky
        )
        _, data, _, _ = run_json(capsys, "--mode", "staged")
        assert SECRET_TOKEN not in json.dumps(data) and data["engine"] == "classic"

    def test_offline_engine_is_covered(self, repo, monkeypatch, capsys):
        leaky = self.leaky()
        monkeypatch.setattr(ReviewCLI, "_run_offline_review", lambda self, args: leaky)
        _, data, _, _ = run_json(capsys, "--offline", "--mode", "staged")
        assert SECRET_TOKEN not in json.dumps(data)

    def test_failure_message_of_the_agent_hides_secrets(
        self, repo, fake_agent, monkeypatch, capsys
    ):
        fake_agent.outcome = result(
            status="error", raw=f"crashed with token={SECRET_HEX}"
        )
        monkeypatch.setattr(
            "review_core.LLMReviewer.review_diff", lambda self, diff: result()
        )
        run_cli("--engine", "agent", "--mode", "staged")
        assert SECRET_HEX not in capsys.readouterr().err

    def test_the_log_has_no_secret(self, repo, fake_agent, monkeypatch):
        monkeypatch.setenv("LLM_MONITORING", "1")
        fake_agent.outcome = self.leaky()
        run_cli("--engine", "agent", "--mode", "staged")
        text = "".join(f.read_text() for f in (Path(repo) / "logs").glob("*.jsonl"))
        assert SECRET_TOKEN not in text and SECRET_HEX not in text
