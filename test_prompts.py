"""Tests for the prompt files and the prompt loader."""

import re
import shutil

import pytest

import prompts
from prompts import load_prompt, render

PROMPT_NAMES = [
    "agent_system",
    "agent_task",
    "agent_diff_shown",
    "agent_diff_missing",
    "agent_nudge",
    "agent_budget_exhausted",
    "agent_project_rules",
    "agent_lang_django",
    "agent_lang_go",
    "agent_lang_rust",
    "classic_review",
    "classic_code_suggestions",
    "rule_docstrings",
    "hybrid_system",
    "hybrid_task",
]
# ASD-STE100 applies to the text that we wrote for the agent.
AGENT_PROMPTS = [
    "agent_system",
    "agent_task",
    "agent_diff_shown",
    "agent_diff_missing",
    "agent_nudge",
    "agent_budget_exhausted",
    "agent_project_rules",
    "agent_lang_django",
    "agent_lang_go",
    "agent_lang_rust",
    "hybrid_system",
    "hybrid_task",
]


class TestFiles:
    @pytest.mark.parametrize("name", PROMPT_NAMES)
    def test_file_exists_and_has_text(self, name):
        path = prompts.PROMPTS_DIR / f"{name}.md"
        assert path.is_file()
        assert load_prompt(name).strip()

    def test_no_unlisted_prompt_files(self):
        found = sorted(p.stem for p in prompts.PROMPTS_DIR.glob("*.md"))
        assert found == sorted(PROMPT_NAMES)

    @pytest.mark.parametrize("name", PROMPT_NAMES)
    def test_loaded_text_has_no_final_newline(self, name):
        assert not load_prompt(name).endswith("\n")

    @pytest.mark.parametrize("name", PROMPT_NAMES)
    def test_files_are_utf8_with_one_final_newline(self, name):
        raw = (prompts.PROMPTS_DIR / f"{name}.md").read_bytes()
        raw.decode("utf-8")
        assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")

    @pytest.mark.parametrize("name", AGENT_PROMPTS)
    def test_agent_sentences_are_short(self, name):
        """ASD-STE100: a sentence has 25 words or fewer."""
        for sentence in re.split(r"(?<=[.:])\s+|\n+", load_prompt(name)):
            assert len(sentence.split()) <= 25, sentence

    def test_agent_prompts_do_not_mention_blocking(self):
        for name in AGENT_PROMPTS:
            text = load_prompt(name).lower()
            # "unsafe block" and "blocking call" in the Rust checks are allowed.
            pattern = r"\bmerge\b|\bblocked\b|block(ing)? (a |the )?(commit|merge|push)"
            assert not re.search(pattern, text), name


class TestPlaceholders:
    def test_agent_placeholders(self):
        assert "{step_target}" in load_prompt("agent_system")
        assert "{project_context}" in load_prompt("agent_system")
        assert "{changed_files}" in load_prompt("agent_task")
        assert "{reason}" in load_prompt("agent_budget_exhausted")

    def test_classic_template_has_every_placeholder(self):
        text = load_prompt("classic_review")
        for name in (
            "diff_content",
            "custom_critical_rules",
            "custom_warnings",
            "custom_suggestions",
            "additional_instructions",
            "code_suggestion_format",
            "context_lines",
        ):
            assert "{" + name + "}" in text

    def test_classic_template_formats_with_str_format(self):
        text = load_prompt("classic_review").format(
            diff_content="D",
            custom_critical_rules="",
            custom_warnings="",
            custom_suggestions="",
            additional_instructions="",
            code_suggestion_format="",
            context_lines=10,
        )
        assert text.endswith("Changes to review:\nD")

    def test_no_unexpected_placeholders_in_agent_prompts(self):
        allowed = {
            "step_target",
            "changed_files",
            "reason",
            "project_context",
            "critical_rules",
            "warning_rules",
            "suggestion_rules",
            "additional_instructions",
            "diff_section",
            "candidates",
            "diffs",
            "files",
        }
        for name in AGENT_PROMPTS:
            assert set(re.findall(r"\{(\w+)\}", load_prompt(name))) <= allowed


class TestLoader:
    def test_missing_file_has_a_clear_error(self):
        with pytest.raises(FileNotFoundError, match="Prompt file not found: .*nope.md"):
            load_prompt("nope")

    def test_reads_from_the_configured_folder(self, tmp_path, monkeypatch):
        (tmp_path / "x.md").write_text("Hello {name}\n\n", encoding="utf-8")
        monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
        assert load_prompt("x") == "Hello {name}"

    def test_same_name_in_another_folder_is_not_mixed_up(self, tmp_path, monkeypatch):
        (tmp_path / "agent_nudge.md").write_text("Other text\n")
        monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
        assert load_prompt("agent_nudge") == "Other text"
        monkeypatch.undo()
        assert load_prompt("agent_nudge") != "Other text"

    def test_render_replaces_only_known_names(self):
        assert render("a {x} b {y} {{z}}", x=1) == "a 1 b {y} {{z}}"

    def test_render_keeps_other_braces(self):
        assert render('{"k": {x}}', x=5) == '{"k": 5}'


class TestPromptsReachTheModel:
    def test_edited_agent_prompt_is_used(self, tmp_path, monkeypatch):
        """A change in a prompt file changes the first request."""
        import subprocess

        from agent_core import AgentReviewer
        from agent_tools import AgentTools
        from config import ReviewConfig
        from diff_parser import DiffParser, RepoSource
        from test_agent_core import FakeClient, submit

        repo = tmp_path / "repo"
        repo.mkdir()
        run = lambda *a: subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=T", *a],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        run("init", "-q", "-b", "main")
        (repo / "a.py").write_text("x = 1\n")
        run("add", ".")
        run("commit", "-q", "-m", "base")
        (repo / "a.py").write_text("x = 2\n")
        run("add", "a.py")
        monkeypatch.chdir(repo)

        folder = tmp_path / "prompts"
        shutil.copytree(prompts.PROMPTS_DIR, folder)
        (folder / "agent_system.md").write_text("CUSTOM SYSTEM {step_target}\n")
        (folder / "agent_task.md").write_text("CUSTOM TASK\n{changed_files}\n")
        monkeypatch.setattr(prompts, "PROMPTS_DIR", folder)

        config = ReviewConfig()
        parser = DiffParser(config)
        parsed = parser.parse_diff(parser.get_diff("staged"))
        tools = AgentTools(config, RepoSource(str(repo), "index"), parser, parsed)
        agent = AgentReviewer(config, client=FakeClient([submit([])]))
        agent.review(tools)
        first = agent.client.requests[0]["messages"]
        assert first[0]["content"] == "CUSTOM SYSTEM 6"
        assert first[1]["content"] == "CUSTOM TASK\na.py (modified) +1 -1"
