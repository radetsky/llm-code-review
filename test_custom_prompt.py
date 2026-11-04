"""Tests for file-based additional_instructions_file prompt loading."""

import json
import logging

from config import ReviewConfig
from review_core import LLMReviewer


def make_config(tmp_path, extra_prompt: dict) -> ReviewConfig:
    """Write a minimal review_config.json under tmp_path and load it.

    Args:
        tmp_path: Pytest tmp_path fixture directory.
        extra_prompt: Dict merged into the ``prompt`` config section.

    Returns:
        Loaded ReviewConfig instance.
    """
    config_data = {"prompt": extra_prompt}
    config_file = tmp_path / "review_config.json"
    config_file.write_text(json.dumps(config_data), encoding="utf-8")
    return ReviewConfig(config_file=str(config_file), explicit=True)


class TestAdditionalInstructionsFile:
    """Tests for ReviewConfig.get_additional_instructions_text()."""

    def test_file_content_returned(self, tmp_path):
        """File content is returned when additional_instructions_file exists."""
        rules_file = tmp_path / "rules.md"
        rules_file.write_text("Always check for null pointers.", encoding="utf-8")
        config = make_config(tmp_path, {"additional_instructions_file": "rules.md"})
        text = config.get_additional_instructions_text()
        assert "Always check for null pointers." in text

    def test_path_resolved_relative_to_config_dir(self, tmp_path):
        """Path is resolved relative to the config file's directory, not CWD."""
        rules_file = tmp_path / "project_rules.md"
        rules_file.write_text("No panic! in production.", encoding="utf-8")
        config = make_config(
            tmp_path, {"additional_instructions_file": "project_rules.md"}
        )
        text = config.get_additional_instructions_text()
        assert "No panic! in production." in text

    def test_missing_file_falls_back_gracefully(self, tmp_path, caplog):
        """Missing file logs a warning and falls back to inline instructions."""
        config = make_config(
            tmp_path,
            {
                "additional_instructions_file": "nonexistent.md",
                "additional_instructions": "inline rule",
            },
        )
        with caplog.at_level(logging.WARNING, logger="config"):
            text = config.get_additional_instructions_text()
        assert "inline rule" in text
        assert any("nonexistent.md" in r.message for r in caplog.records)

    def test_file_and_inline_combined(self, tmp_path):
        """File content and inline additional_instructions are concatenated."""
        rules_file = tmp_path / "rules.md"
        rules_file.write_text("File rule.", encoding="utf-8")
        config = make_config(
            tmp_path,
            {
                "additional_instructions_file": "rules.md",
                "additional_instructions": "Inline rule.",
            },
        )
        text = config.get_additional_instructions_text()
        assert "File rule." in text
        assert "Inline rule." in text
        assert text.index("File rule.") < text.index("Inline rule.")

    def test_no_keys_returns_empty_string(self, tmp_path):
        """Returns empty string when neither key is set."""
        config = make_config(tmp_path, {})
        assert config.get_additional_instructions_text() == ""

    def test_braces_in_file_do_not_raise(self, tmp_path):
        """Curly braces in the file content do not cause KeyError in .format()."""
        rules_file = tmp_path / "rules.md"
        rules_file.write_text(
            "Pass args as { req } always. Match arms: _ => {}.", encoding="utf-8"
        )
        config = make_config(tmp_path, {"additional_instructions_file": "rules.md"})
        reviewer = LLMReviewer(config)
        prompt = reviewer._build_system_prompt()
        assert "{ req }" in prompt


class TestSystemPromptWithFile:
    """Tests for LLMReviewer._build_system_prompt() when a file is loaded."""

    def test_file_content_appears_before_format_block(self, tmp_path):
        """Project rules from file appear in the system prompt before the Format: block."""
        rules_file = tmp_path / "rules.md"
        rules_file.write_text("No unwrap() in production.", encoding="utf-8")
        config = make_config(tmp_path, {"additional_instructions_file": "rules.md"})
        reviewer = LLMReviewer(config)
        prompt = reviewer._build_system_prompt()
        assert "No unwrap() in production." in prompt
        format_block = "Format:\nCRITICAL: file.py:42:"
        assert format_block in prompt
        assert prompt.index("No unwrap() in production.") < prompt.index(format_block)

    def test_built_in_format_contract_still_present(self, tmp_path):
        """CRITICAL:/WARNING: format contract is always in the prompt regardless of file."""
        rules_file = tmp_path / "rules.md"
        rules_file.write_text("Custom rule.", encoding="utf-8")
        config = make_config(tmp_path, {"additional_instructions_file": "rules.md"})
        reviewer = LLMReviewer(config)
        prompt = reviewer._build_system_prompt()
        assert "CRITICAL: file.py:42:" in prompt
        assert "WARNING: file.py:15:" in prompt

    def test_format_authority_lead_in_present(self, tmp_path):
        """The lead-in that asserts format authority is injected before the file content."""
        rules_file = tmp_path / "rules.md"
        rules_file.write_text("Project rule.", encoding="utf-8")
        config = make_config(tmp_path, {"additional_instructions_file": "rules.md"})
        reviewer = LLMReviewer(config)
        prompt = reviewer._build_system_prompt()
        assert "ALWAYS report findings" in prompt
        assert prompt.index("ALWAYS report findings") < prompt.index("Project rule.")

    def test_no_file_lead_in_absent(self, tmp_path):
        """Without additional_instructions_file the lead-in is not injected."""
        config = make_config(tmp_path, {"additional_instructions": "inline rule"})
        reviewer = LLMReviewer(config)
        prompt = reviewer._build_system_prompt()
        assert "CRITICAL: file.py:42:" in prompt
        assert "ALWAYS report findings" not in prompt
