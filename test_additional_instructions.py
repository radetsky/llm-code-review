"""Tests for prompt.additional_instructions_file."""

import json
import logging

import pytest

from config import ReviewConfig
from prompts import collect_rules


def make_config(tmp_path, prompt):
    path = tmp_path / "review_config.json"
    path.write_text(json.dumps({"prompt": prompt}), encoding="utf-8")
    return ReviewConfig(str(path))


def test_file_text_is_returned(tmp_path):
    (tmp_path / "rules.md").write_text("Check null pointers.\n", encoding="utf-8")
    config = make_config(tmp_path, {"additional_instructions_file": "rules.md"})
    assert config.get_additional_instructions_text() == "Check null pointers."


def test_path_starts_at_config_folder(tmp_path, monkeypatch):
    (tmp_path / "rules.md").write_text("Rule.", encoding="utf-8")
    config = make_config(tmp_path, {"additional_instructions_file": "rules.md"})
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert config.get_additional_instructions_text() == "Rule."


def test_file_text_comes_before_inline_text(tmp_path):
    (tmp_path / "rules.md").write_text("File rule.", encoding="utf-8")
    config = make_config(
        tmp_path,
        {
            "additional_instructions_file": "rules.md",
            "additional_instructions": "Inline rule.",
        },
    )
    text = config.get_additional_instructions_text()
    assert text.index("File rule.") < text.index("Inline rule.")


def test_missing_file_uses_inline_text(tmp_path, caplog):
    config = make_config(
        tmp_path,
        {
            "additional_instructions_file": "missing.md",
            "additional_instructions": "Inline rule.",
        },
    )
    with caplog.at_level(logging.WARNING, logger="config"):
        assert config.get_additional_instructions_text() == "Inline rule."
    assert any("missing.md" in r.getMessage() for r in caplog.records)


def test_no_keys_return_empty_text(tmp_path):
    assert make_config(tmp_path, {}).get_additional_instructions_text() == ""


@pytest.mark.parametrize("engine_text", ["Match arms: _ => {}."])
def test_collect_rules_includes_file_text(tmp_path, engine_text):
    (tmp_path / "rules.md").write_text(engine_text, encoding="utf-8")
    config = make_config(tmp_path, {"additional_instructions_file": "rules.md"})
    assert collect_rules(config)["additional"] == engine_text
