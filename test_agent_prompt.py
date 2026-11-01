"""Tests for the system prompt builder: language checks and project rules."""

import re
import subprocess

import pytest

from agent_prompt import (
    LANGUAGE_BLOCKS,
    build_system_prompt,
    detect_language_blocks,
    render_project_rules,
)
from config import ReviewConfig
from prompts import collect_rules, load_prompt
from test_agent_core import (  # noqa: F401  (fixtures)
    FakeClient,
    run,
    submit,
    tools,
)


def files(*paths):
    return [{"path": p, "type": "modified", "hunks": []} for p in paths]


class FakeSource:
    """Knows which files exist, like RepoSource.find_files."""

    def __init__(self, *existing):
        self.existing = existing

    def find_files(self, pattern, max_results=200):
        return [f for f in self.existing if f.split("/")[-1] == pattern][:max_results]


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # No review_config.json in this folder.
    return ReviewConfig()


def set_prompt(config, **values):
    config.config["prompt"].update(values)


class TestCollectRules:
    def test_defaults_have_only_the_docstring_rule(self, config):
        rules = collect_rules(config)
        assert rules["critical"] == "" and rules["warnings"] == ""
        assert rules["suggestions"] == "- " + load_prompt("rule_docstrings")
        assert rules["additional"] == ""

    def test_custom_rules_become_bullets(self, config):
        set_prompt(
            config,
            custom_critical_rules=["leaks", "races"],
            custom_warnings=["deprecated"],
            additional_instructions="Focus on threads",
        )
        rules = collect_rules(config)
        assert rules["critical"] == "- leaks\n- races"
        assert rules["warnings"] == "- deprecated"
        assert rules["additional"] == "Focus on threads"

    def test_docstring_rule_can_be_switched_off(self, config):
        config.config["review"]["check_docstrings"] = False
        assert collect_rules(config)["suggestions"] == ""

    def test_docstring_rule_is_not_added_twice(self, config):
        set_prompt(config, custom_suggestions=[load_prompt("rule_docstrings")])
        assert collect_rules(config)["suggestions"].count("Flag missing") == 1

    def test_config_is_not_changed(self, config):
        set_prompt(config, custom_suggestions=["a"])
        collect_rules(config)
        collect_rules(config)
        assert config.get("prompt.custom_suggestions") == ["a"]

    def test_bad_values_are_ignored(self, config):
        set_prompt(
            config,
            custom_critical_rules="not a list",
            custom_warnings=["ok", 5, None],
            additional_instructions=7,
        )
        rules = collect_rules(config)
        assert rules["critical"] == "" and rules["warnings"] == "- ok"
        assert rules["additional"] == ""


class TestProjectRules:
    def test_empty_sections_are_left_out(self, config):
        config.config["review"]["check_docstrings"] = False
        assert render_project_rules(config) == ""

    def test_only_filled_sections_appear(self, config):
        config.config["review"]["check_docstrings"] = False
        set_prompt(config, custom_critical_rules=["leaks"])
        text = render_project_rules(config)
        assert text == "Project rules. Report these problems as critical:\n- leaks"

    def test_all_sections(self, config):
        set_prompt(
            config,
            custom_critical_rules=["a"],
            custom_warnings=["b"],
            custom_suggestions=["c"],
            additional_instructions="  d  ",
        )
        text = render_project_rules(config)
        assert text.index("critical:\n- a") < text.index("warnings:\n- b")
        assert text.index("warnings:\n- b") < text.index("suggestions:\n- c")
        assert text.endswith("Additional instructions from the project:\nd")
        assert "{" not in text


class TestLanguageDetection:
    def test_auto_from_extensions(self, config):
        got = detect_language_blocks(
            config, files("a.rs", "b.go", "c.js"), FakeSource()
        )
        assert got == ["go", "rust"]

    def test_auto_finds_nothing_for_other_files(self, config):
        assert detect_language_blocks(config, files("a.js", "b.ts"), FakeSource()) == []

    def test_django_needs_manage_py_and_a_python_file(self, config):
        with_manage = FakeSource("site/manage.py")
        assert detect_language_blocks(config, files("app/views.py"), with_manage) == [
            "django"
        ]
        assert detect_language_blocks(config, files("app/views.py"), FakeSource()) == []
        assert detect_language_blocks(config, files("app/x.js"), with_manage) == []

    def test_explicit_list(self, config):
        set_prompt(config, language_blocks=["rust", "django", "rust"])
        assert detect_language_blocks(config, files("a.js"), FakeSource()) == [
            "rust",
            "django",
        ]

    def test_empty_list_switches_checks_off(self, config):
        set_prompt(config, language_blocks=[])
        assert detect_language_blocks(config, files("a.rs"), FakeSource()) == []

    def test_unknown_name_is_ignored_with_a_warning(self, config, caplog):
        set_prompt(config, language_blocks=["cobol", "go"])
        assert detect_language_blocks(config, files("a.js"), FakeSource()) == ["go"]
        assert "Unknown language check 'cobol'" in caplog.text

    def test_wrong_type_is_ignored_with_a_warning(self, config, caplog):
        set_prompt(config, language_blocks="rust")
        assert detect_language_blocks(config, files("a.rs"), FakeSource()) == []
        assert "must be 'auto' or a list" in caplog.text

    def test_every_block_has_a_prompt_file(self):
        for name in LANGUAGE_BLOCKS:
            assert load_prompt(f"agent_lang_{name}").startswith(
                f"{name.capitalize()} checks:"
            )


class TestBuildSystemPrompt:
    def build(self, config, paths=("a.py",), source=None, target=6):
        return build_system_prompt(
            config, files(*paths), source or FakeSource(), target
        )

    def test_plain_prompt_has_no_placeholders_and_no_gap(self, config):
        config.config["review"]["check_docstrings"] = False
        text = self.build(config)
        assert not re.search(r"\{\w+\}", text)
        assert "\n\n\n" not in text
        assert "Try to finish in 6 steps or fewer." in text
        assert "checks:" not in text and "Project rules" not in text

    def test_language_block_comes_before_the_efficiency_rules(self, config):
        text = self.build(config, paths=("lib.rs",))
        assert "Rust checks:" in text
        assert text.index("Rust checks:") < text.index("Work efficiently")
        assert text.index("Example of a clean review") < text.index("Rust checks:")

    def test_blocks_and_rules_together(self, config):
        set_prompt(config, custom_warnings=["no print"])
        text = self.build(config, paths=("a.go", "b.rs"))
        order = [text.index(k) for k in ("Go checks:", "Rust checks:", "Project rules")]
        assert order == sorted(order)

    def test_docstring_rule_reaches_the_agent_by_default(self, config):
        assert "Flag missing docstrings" in self.build(config)


class TestReachTheModel:
    def test_first_request_has_blocks_and_rules(self, tools):  # noqa: F811
        tools.config.config["prompt"].update(
            custom_critical_rules=["no eval"], language_blocks=["go"]
        )
        _, client = run(tools, [submit([])])
        system = client.requests[0]["messages"][0]["content"]
        assert "Go checks:" in system
        assert "Project rules. Report these problems as critical:\n- no eval" in system
        assert "Try to finish in 6 steps or fewer." in system
        assert not re.search(r"\{\w+\}", system)

    def test_django_is_found_from_the_real_repository(self, tools, tmp_path):  # noqa: F811
        (tmp_path / "manage.py").write_text("# django\n")
        subprocess.run(["git", "add", "manage.py"], cwd=tmp_path, check=True)
        _, client = run(tools, [submit([])])
        assert "Django checks:" in client.requests[0]["messages"][0]["content"]

    def test_no_block_without_manage_py(self, tools):  # noqa: F811
        _, client = run(tools, [submit([])])
        assert "Django checks:" not in client.requests[0]["messages"][0]["content"]

    def test_prompt_edits_apply(self, tools, monkeypatch):  # noqa: F811
        import prompts

        original = prompts.load_prompt

        def patched(name):
            return (
                "ONLY {project_context} {step_target}"
                if name == "agent_system"
                else original(name)
            )

        monkeypatch.setattr("agent_prompt.load_prompt", patched)
        tools.config.config["prompt"]["language_blocks"] = ["rust"]
        _, client = run(tools, [submit([])])
        system = client.requests[0]["messages"][0]["content"]
        assert system.startswith("ONLY Rust checks:")
        assert system.endswith(" 6")
