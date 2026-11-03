"""Tests for the GitHub Action: the manifest, its scripts and its dependencies."""

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent
ACTION = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
STEPS = ACTION["runs"]["steps"]
sys.path.insert(0, str(ROOT / "scripts"))
import read_result

RUNTIME_MODULES = (
    "review.py",
    "config.py",
    "diff_parser.py",
    "review_core.py",
    "agent_core.py",
    "agent_tools.py",
    "agent_prompt.py",
    "prompts.py",
    "static_analyzer.py",
)


def step(name: str) -> dict:
    return next(s for s in STEPS if s["name"] == name)


# -- dependencies ----------------------------------------------------------


class TestDependencies:
    def third_party_imports(self) -> set[str]:
        local = {p.stem for p in ROOT.glob("*.py")}
        found = set()
        for module in RUNTIME_MODULES:
            for node in ast.walk(
                ast.parse((ROOT / module).read_text(encoding="utf-8"))
            ):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif (
                    isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                ):
                    names = [node.module.split(".")[0]]
                else:
                    continue
                found |= {
                    n
                    for n in names
                    if n not in sys.stdlib_module_names and n not in local
                }
        return found

    def test_action_requirements_cover_the_runtime_imports(self):
        lines = (ROOT / "requirements-action.txt").read_text().splitlines()
        listed = {
            re.split(r"[<>=!~ ]", l)[0].lower()
            for l in lines
            if l.strip() and not l.startswith("#")
        }
        missing = self.third_party_imports() - listed
        assert not missing, f"requirements-action.txt does not list: {sorted(missing)}"

    def test_the_action_installs_that_file(self):
        install = step("Install dependencies")["run"]
        assert "requirements-action.txt" in install


# -- manifest rules --------------------------------------------------------


def all_scripts() -> list[tuple[str, str]]:
    """The text of every run block and every github-script block."""
    scripts = []
    for s in STEPS:
        if "run" in s:
            scripts.append((s["name"], s["run"]))
        if "script" in (s.get("with") or {}):
            scripts.append((s["name"], s["with"]["script"]))
    return scripts


class TestManifest:
    def test_no_workflow_expression_in_a_script(self):
        """A ${{ }} expression in a script runs as code. Values go through env."""
        for name, text in all_scripts():
            assert "${{" not in text, f"{name}: use env instead of an expression"

    def test_old_blocking_options_are_gone(self):
        text = (ROOT / "action.yml").read_text(encoding="utf-8")
        assert "REQUEST_CHANGES" not in text
        assert (
            "fail_on_critical" not in ACTION["inputs"]
            and "strict" not in ACTION["inputs"]
        )
        assert not any("failures" in s["name"].lower() for s in STEPS)

    def test_no_step_can_fail_the_job(self):
        for name, text in all_scripts():
            assert not re.search(r"\bexit\s+[1-9]", text), f"{name} exits with an error"
        for name in (
            "Run LLM Code Review",
            "Post PR Comment",
            "Post Inline Review Comments",
            "Fetch the commits of the diff",
        ):
            assert step(name).get("continue-on-error") is True, name

    def test_every_run_step_names_a_shell(self):
        for s in STEPS:
            if "run" in s:
                assert s.get("shell") == "bash", s["name"]

    def test_inputs_used_in_the_file_are_declared(self):
        text = (ROOT / "action.yml").read_text(encoding="utf-8")
        used = set(re.findall(r"\binputs\.(\w+)", text))
        assert used <= set(ACTION["inputs"]), used - set(ACTION["inputs"])

    def test_new_inputs(self):
        inputs = ACTION["inputs"]
        assert inputs["engine"]["default"] == "classic"
        assert "max_steps" in inputs and "wall_timeout" in inputs
        assert "thinking" in inputs and not inputs["thinking"].get("default")
        assert inputs["api_key"]["required"] is False  # An empty key skips the review.

    def test_outputs_point_to_existing_steps(self):
        ids = {s["id"] for s in STEPS if "id" in s}
        for name, output in ACTION["outputs"].items():
            for step_id in re.findall(r"steps\.(\w+)\.outputs", output["value"]):
                assert step_id in ids, f"{name}: {step_id}"

    def test_actions_are_pinned_to_a_version(self):
        for s in STEPS:
            if "uses" in s:
                assert re.search(r"@v\d+(\.\d+)*$", s["uses"]), s["uses"]

    def test_files_that_the_action_uses_exist(self):
        text = (ROOT / "action.yml").read_text(encoding="utf-8")
        for relative in set(
            re.findall(r"(?:ACTION_PATH|action_path)[}\"]*/([\w./-]+)", text)
        ):
            assert (ROOT / relative).exists(), relative

    def test_comment_steps_run_on_pull_requests_only(self):
        for name in ("Post PR Comment", "Post Inline Review Comments"):
            assert "github.event_name == 'pull_request'" in step(name)["if"]

    def test_posting_steps_run_after_a_failed_review(self):
        for name in ("Post PR Comment", "Post Inline Review Comments"):
            assert step(name)["if"].startswith("always()")

    def test_nothing_runs_without_a_key(self):
        for s in STEPS[1:]:
            if s["name"] in (
                "Show the result",
                "Post PR Comment",
                "Post Inline Review Comments",
                "Setup Python",
            ):
                assert "steps.settings.outputs.run == 'true'" in s["if"], s["name"]


# -- the bash steps of the manifest ---------------------------------------


def run_step(name: str, env: dict, tmp_path: Path, cwd: Path | None = None) -> dict:
    """Run the script of a step and return what it wrote to GITHUB_OUTPUT."""
    output = tmp_path / "github_output"
    output.write_text("")
    script = tmp_path / "step.sh"
    script.write_text(step(name)["run"])
    proc = subprocess.run(
        ["bash", "-e", str(script)],
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GITHUB_OUTPUT": str(output),
            "RUNNER_TEMP": str(tmp_path),
            **env,
        },
        cwd=cwd or tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    values = {}
    for line in output.read_text().splitlines():
        key, _, value = line.partition("=")
        values[key] = value
    values["_exit"] = proc.returncode
    values["_out"] = proc.stdout + proc.stderr
    return values


SETTINGS_ENV = {
    "API_KEY": "key",
    "INPUT_ENGINE": "classic",
    "INPUT_MODE": "",
    "INPUT_THINKING": "",
    "INPUT_MAX_STEPS": "",
    "INPUT_WALL_TIMEOUT": "",
    "INPUT_CONTEXT": "",
}


class TestSettingsStep:
    def run(self, tmp_path, **override):
        return run_step("Check settings", {**SETTINGS_ENV, **override}, tmp_path)

    def test_no_key_skips_quietly(self, tmp_path):
        out = self.run(tmp_path, API_KEY="")
        assert out["_exit"] == 0
        assert (out["run"], out["status"], out["outcome"]) == (
            "false",
            "skipped",
            "none",
        )
        assert "::notice::" in out["_out"]

    def test_normal_values(self, tmp_path):
        out = self.run(
            tmp_path,
            INPUT_ENGINE="agent",
            INPUT_MAX_STEPS="12",
            INPUT_WALL_TIMEOUT="90",
            INPUT_CONTEXT="5",
        )
        assert out["run"] == "true" and out["engine"] == "agent"
        assert (out["max_steps"], out["wall_timeout"], out["context"]) == (
            "12",
            "90",
            "5",
        )

    def test_defaults_are_empty(self, tmp_path):
        out = self.run(tmp_path)
        assert (
            out["engine"],
            out["mode"],
            out["max_steps"],
            out["wall_timeout"],
            out["context"],
        ) == ("classic", "", "", "", "")

    def test_hybrid_engine_is_accepted(self, tmp_path):
        out = self.run(tmp_path, INPUT_ENGINE="hybrid")
        assert out["engine"] == "hybrid"

    @pytest.mark.parametrize(
        "engine", ["turbo", "AGENT", "agent; rm -rf /", "$(id)", ""]
    )
    def test_unknown_engine_becomes_classic(self, tmp_path, engine):
        out = self.run(tmp_path, INPUT_ENGINE=engine)
        assert out["engine"] == "classic" and out["_exit"] == 0

    @pytest.mark.parametrize("value", ["0", "-3", "abc", "1.5", "5; id", "$(id)", " 7"])
    def test_bad_numbers_are_ignored(self, tmp_path, value):
        out = self.run(
            tmp_path,
            INPUT_MAX_STEPS=value,
            INPUT_WALL_TIMEOUT=value,
            INPUT_CONTEXT=value,
        )
        assert (out["max_steps"], out["wall_timeout"], out["context"]) == ("", "", "")
        assert out["_exit"] == 0

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("on", "on"),
            ("off", "off"),
            ("default", "default"),
            ("", ""),
            ("ON", ""),
            ("yes", ""),
            ("on; id", ""),
            ("$(id)", ""),
        ],
    )
    def test_thinking(self, tmp_path, value, expected):
        out = self.run(tmp_path, INPUT_THINKING=value)
        assert out["thinking"] == expected and out["_exit"] == 0

    @pytest.mark.parametrize(
        "mode,expected",
        [("staged", "staged"), ("all", "all"), ("--x", ""), ("a b", "")],
    )
    def test_mode(self, tmp_path, mode, expected):
        assert self.run(tmp_path, INPUT_MODE=mode)["mode"] == expected

    def test_the_key_is_not_printed(self, tmp_path):
        out = self.run(tmp_path, API_KEY="super-secret-value")
        assert "super-secret-value" not in out["_out"]


RANGE_ENV = {
    "INPUT_BASE": "",
    "INPUT_HEAD": "",
    "EVENT_NAME": "pull_request",
    "PR_BASE": "aaa111",
    "PR_HEAD": "bbb222",
    "PUSH_BEFORE": "ccc333",
    "PUSH_SHA": "ddd444",
}


class TestDiffRangeStep:
    def run(self, tmp_path, **override):
        return run_step("Determine diff range", {**RANGE_ENV, **override}, tmp_path)

    def test_pull_request(self, tmp_path):
        out = self.run(tmp_path)
        assert (out["base"], out["head"]) == ("aaa111", "bbb222")

    def test_push(self, tmp_path):
        out = self.run(tmp_path, EVENT_NAME="push")
        assert (out["base"], out["head"]) == ("ccc333", "ddd444")

    def test_other_event(self, tmp_path):
        out = self.run(tmp_path, EVENT_NAME="workflow_dispatch")
        assert (out["base"], out["head"]) == ("HEAD~1", "HEAD")

    def test_inputs_win(self, tmp_path):
        out = self.run(tmp_path, INPUT_BASE="main", INPUT_HEAD="feature")
        assert (out["base"], out["head"]) == ("main", "feature")

    def test_one_input_alone_is_not_enough(self, tmp_path):
        out = self.run(tmp_path, INPUT_BASE="main")
        assert (out["base"], out["head"]) == ("aaa111", "bbb222")

    @pytest.mark.parametrize(
        "bad", ["--output=/tmp/x", "-p", "0000000000000000000000000000000000000000", ""]
    )
    def test_bad_base(self, tmp_path, bad):
        out = self.run(
            tmp_path,
            INPUT_BASE=bad,
            INPUT_HEAD="feature",
            PR_BASE=bad,
            EVENT_NAME="pull_request",
        )
        assert out["base"] == "HEAD~1"

    def test_bad_head(self, tmp_path):
        out = self.run(tmp_path, PR_HEAD="--output=/tmp/x")
        assert out["head"] == "HEAD"

    def test_new_branch_push_uses_the_previous_commit(self, tmp_path):
        out = self.run(tmp_path, EVENT_NAME="push", PUSH_BEFORE="0" * 40)
        assert out["base"] == "HEAD~1" and out["head"] == "ddd444"


FAKE_REVIEW = """
import json, os, sys
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "crash":
    print("Error: boom happened", file=sys.stderr)
    sys.exit(4)
if mode == "garbage":
    print("not json")
    sys.exit(0)
json.dump({
    "status": "success", "review_outcome": "warnings", "engine": sys.argv[sys.argv.index("--engine") + 1],
    "critical_issues": [], "warnings": ["a.py:1: w"], "suggestions": [], "code_suggestions": [],
    "argv": sys.argv[1:],
}, sys.stdout)
"""


@pytest.fixture
def fake_action(tmp_path):
    """A copy of the action folder with a fake review.py."""
    path = tmp_path / "action"
    (path / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "read_result.py", path / "scripts")
    (path / "review.py").write_text(FAKE_REVIEW)
    return path


REVIEW_ENV = {
    "LLM_API_KEY": "k",
    "ENGINE": "agent",
    "MODE": "",
    "THINKING": "",
    "MAX_STEPS": "",
    "WALL_TIMEOUT": "",
    "CONTEXT": "",
    "BASE": "aaa",
    "HEAD": "bbb",
    "PYTHONDONTWRITEBYTECODE": "1",
}


class TestReviewStep:
    def run(self, tmp_path, fake_action, **override):
        env = {
            **REVIEW_ENV,
            "ACTION_PATH": str(fake_action),
            "PATH": "/usr/bin:/bin:/usr/local/bin:" + str(Path(sys.executable).parent),
            **override,
        }
        out = run_step("Run LLM Code Review", env, tmp_path)
        out["_result"] = (
            json.loads(Path(out["result_file"]).read_text())
            if out.get("result_file")
            and Path(out["result_file"]).read_text().strip().startswith("{")
            else None
        )
        return out

    def test_success_outputs(self, tmp_path, fake_action):
        out = self.run(tmp_path, fake_action)
        assert out["_exit"] == 0
        assert (out["status"], out["outcome"], out["engine"]) == (
            "success",
            "warnings",
            "agent",
        )
        assert (
            out["critical_count"],
            out["warning_count"],
            out["suggestion_count"],
        ) == ("0", "1", "0")
        assert out["error"] == ""

    def test_arguments(self, tmp_path, fake_action):
        out = self.run(
            tmp_path, fake_action, MAX_STEPS="9", WALL_TIMEOUT="60", CONTEXT="4"
        )
        argv = out["_result"]["argv"]
        assert argv[:4] == ["--format", "json", "--engine", "agent"]
        assert (
            argv[argv.index("--base") + 1] == "aaa"
            and argv[argv.index("--head") + 1] == "bbb"
        )
        assert argv[argv.index("--max-steps") + 1] == "9"
        assert argv[argv.index("--wall-timeout") + 1] == "60"
        assert argv[argv.index("--context") + 1] == "4"

    def test_thinking_is_passed_only_when_it_is_set(self, tmp_path, fake_action):
        argv = self.run(tmp_path, fake_action, THINKING="on")["_result"]["argv"]
        assert argv[argv.index("--thinking") + 1] == "on"
        assert "--thinking" not in self.run(tmp_path, fake_action)["_result"]["argv"]

    def test_mode_replaces_the_range(self, tmp_path, fake_action):
        argv = self.run(tmp_path, fake_action, MODE="staged")["_result"]["argv"]
        assert "--mode" in argv and "--base" not in argv

    def test_values_are_never_run_as_commands(self, tmp_path, fake_action):
        marker = tmp_path / "pwned"
        evil = f"$(touch {marker})"
        out = self.run(
            tmp_path,
            fake_action,
            BASE=evil,
            HEAD=f"`touch {marker}`",
            MODE="",
            CONTEXT=f"; touch {marker}",
        )
        assert not marker.exists()
        assert (
            out["_result"]["argv"][out["_result"]["argv"].index("--base") + 1] == evil
        )

    def test_values_with_spaces_stay_one_argument(self, tmp_path, fake_action):
        out = self.run(tmp_path, fake_action, MODE="staged --output=/tmp/x")
        argv = out["_result"]["argv"]
        assert argv[argv.index("--mode") + 1] == "staged --output=/tmp/x"
        out = self.run(tmp_path, fake_action, BASE="a b", HEAD="c d")
        argv = out["_result"]["argv"]
        assert (argv[argv.index("--base") + 1], argv[argv.index("--head") + 1]) == (
            "a b",
            "c d",
        )

    def test_a_crash_becomes_an_error_output_and_the_step_succeeds(
        self, tmp_path, fake_action
    ):
        out = self.run(tmp_path, fake_action, FAKE_MODE="crash")
        assert out["_exit"] == 0
        assert out["status"] == "error" and out["outcome"] == "none"
        assert out["error"] == "Error: boom happened"

    def test_garbage_output_becomes_an_error(self, tmp_path, fake_action):
        out = self.run(tmp_path, fake_action, FAKE_MODE="garbage")
        assert out["_exit"] == 0 and out["status"] == "error"

    def test_missing_review_script_is_still_not_a_failure(self, tmp_path, fake_action):
        (fake_action / "review.py").unlink()
        out = self.run(tmp_path, fake_action)
        assert out["_exit"] == 0 and out["status"] == "error"


# -- read_result.py --------------------------------------------------------


class TestReadResult:
    def write(self, tmp_path, data):
        path = tmp_path / "result.json"
        path.write_text(data if isinstance(data, str) else json.dumps(data))
        return str(path)

    def test_counts(self, tmp_path):
        path = self.write(
            tmp_path,
            {
                "status": "success",
                "review_outcome": "critical",
                "engine": "agent->classic",
                "critical_issues": ["a", "b"],
                "warnings": ["c"],
                "suggestions": ["d"],
                "code_suggestions": [{"file": "x"}, {"file": "y"}],
            },
        )
        out = read_result.summarize(path, str(tmp_path / "none"), "0")
        assert out["critical_count"] == 2 and out["warning_count"] == 1
        assert out["suggestion_count"] == 3  # One suggestion and two code suggestions.
        assert (out["outcome"], out["engine"], out["error"]) == (
            "critical",
            "agent->classic",
            "",
        )

    def test_a_model_that_was_not_available_has_no_outcome(self, tmp_path):
        path = self.write(
            tmp_path,
            {
                "status": "model_unavailable",
                "review_outcome": "warnings",
                "warnings": ["x"],
            },
        )
        out = read_result.summarize(path, "", "0")
        assert out["status"] == "model_unavailable" and out["outcome"] == "none"

    @pytest.mark.parametrize("content", ["", "not json", "[1, 2]", "null", '"text"'])
    def test_bad_result_files(self, tmp_path, content):
        err = tmp_path / "err.txt"
        err.write_text("first line\n\nlast line with the reason\n\n")
        out = read_result.summarize(self.write(tmp_path, content), str(err), "4")
        assert out["status"] == "error" and out["error"] == "last line with the reason"
        assert out["critical_count"] == out["warning_count"] == 0

    def test_missing_files(self, tmp_path):
        out = read_result.summarize(
            str(tmp_path / "no.json"), str(tmp_path / "no.txt"), "124"
        )
        assert out["status"] == "error" and "code 124" in out["error"]

    def test_secrets_in_the_error_line_are_hidden(self, tmp_path):
        err = tmp_path / "err.txt"
        err.write_text(
            "Error: request failed with token=4f9c2a7e61b84d3f9a05c8d17e2b6a43\n"
        )
        out = read_result.summarize(str(tmp_path / "no.json"), str(err), "1")
        assert "4f9c2a7e61b84d3f9a05c8d17e2b6a43" not in out["error"]
        assert "[REDACTED]" in out["error"]

    def test_the_message_is_on_one_line_and_short(self, tmp_path):
        err = tmp_path / "err.txt"
        err.write_text("x" * 1000)
        out = read_result.summarize(str(tmp_path / "no.json"), str(err), "1")
        assert len(out["error"]) == 300
        err.write_text("a\tb   c")
        assert (
            read_result.summarize(str(tmp_path / "no.json"), str(err), "1")["error"]
            == "a b c"
        )

    def test_main_prints_key_value_lines(self, tmp_path, capsys):
        path = self.write(tmp_path, {"status": "success", "review_outcome": "success"})
        assert read_result.main(["x", path, "", "0"]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert (
            "status=success" in lines
            and "outcome=success" in lines
            and "error=" in lines
        )
        assert all("=" in line for line in lines)

    def test_main_needs_three_arguments(self):
        assert read_result.main(["x"]) == 2


# -- the JavaScript tests --------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_javascript_tests_pass():
    proc = subprocess.run(
        ["node", "--test", str(ROOT / "scripts" / "post_review.test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1000:]


# -- the workflows and the examples ---------------------------------------

WORKFLOW_FILES = sorted(
    [*ROOT.glob("examples/*.yml"), *ROOT.glob(".github/workflows/*.yml")]
)


def action_calls(path: Path):
    """Yield (job, step) for each step that uses this action."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for job_name, job in data["jobs"].items():
        for item in job.get("steps", []):
            uses = item.get("uses", "")
            if uses == "./" or uses.startswith("radetsky/llm-code-review@"):
                yield job_name, item


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
class TestWorkflows:
    def test_only_declared_inputs_are_used(self, path):
        for _, item in action_calls(path):
            assert set(item["with"]) <= set(ACTION["inputs"]), item["with"]

    def test_removed_inputs_are_not_used(self, path):
        text = path.read_text(encoding="utf-8")
        assert "fail_on_critical" not in text and "strict:" not in text

    def test_no_expression_in_a_run_script(self, path):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in data["jobs"].values():
            for item in job.get("steps", []):
                assert "${{" not in item.get("run", ""), item.get("name")

    def test_jobs_have_a_time_limit(self, path):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in data["jobs"].items():
            if any(True for _ in action_calls(path)):
                assert "timeout-minutes" in job, name

    def test_jobs_that_review_check_out_the_full_history(self, path):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in data["jobs"].values():
            uses_action = any(
                i.get("uses", "") == "./" or i.get("uses", "").startswith("radetsky/")
                for i in job.get("steps", [])
            )
            if uses_action:
                checkout = next(
                    i
                    for i in job["steps"]
                    if i.get("uses", "").startswith("actions/checkout")
                )
                assert checkout["with"]["fetch-depth"] == 0

    def test_never_pull_request_target(self, path):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = data.get("on") or data.get(True)
        assert "pull_request_target" not in triggers


def test_the_self_test_runs_both_engines_with_separate_comments():
    path = ROOT / ".github" / "workflows" / "llm_code_review.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    job = data["jobs"]["self-review"]
    assert job["strategy"]["matrix"]["engine"] == ["classic", "agent"]
    assert job["strategy"]["fail-fast"] is False
    assert job["continue-on-error"] is True
    ((_, call),) = list(action_calls(path))
    assert call["with"]["engine"] == "${{ matrix.engine }}"
    assert call["with"]["comment_tag"] == "${{ matrix.engine }}"
    checkout = next(i for i in job["steps"] if i["uses"].startswith("actions/checkout"))
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"


def test_readme_documents_every_input_and_output():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in ACTION["inputs"]:
        assert f"`{name}`" in text, f"README does not describe the input {name}"
    for name in ACTION["outputs"]:
        assert f"`{name}`" in text, f"README does not describe the output {name}"
