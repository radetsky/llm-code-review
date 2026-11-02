"""Checks on the data files of the repository."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent


def tracked_json_files() -> list[Path]:
    names = subprocess.run(
        ["git", "ls-files", "*.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [ROOT / n for n in names]


@pytest.mark.parametrize(
    "path", tracked_json_files(), ids=lambda p: str(p.relative_to(ROOT))
)
def test_json_file_is_valid(path):
    """A formatter can add trailing commas. Plain JSON does not allow them."""
    json.loads(path.read_text(encoding="utf-8"))


def test_example_configs_use_a_known_provider_only():
    for name in ("review_config_example.json", "review_config_rust_example.json"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "opencode" not in text and "anthropic/" not in text, name
