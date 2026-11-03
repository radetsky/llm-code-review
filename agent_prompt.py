"""
Build the system prompt of the review agent.

The base text is in prompts/agent_system.md. This module adds the optional
language checks and the project rules from the config.
"""

import logging
import re

from prompts import collect_rules, load_prompt, render

logger = logging.getLogger(__name__)

# Language checks that exist as prompts/agent_lang_<name>.md.
LANGUAGE_BLOCKS = ("django", "go", "rust")
FILE_EXTENSIONS = {".rs": "rust", ".go": "go"}


def detect_language_blocks(config, parsed_files: list[dict], source) -> list[str]:
    """Return the names of the language checks for this review.

    The config key prompt.language_blocks controls the result:
    "auto" (default) selects checks from the changed files, a list names the
    checks, and an empty list selects none.
    """
    setting = config.get("prompt.language_blocks", "auto")
    if setting == "auto":
        names = set()
        paths = [f["path"] for f in parsed_files]
        for path in paths:
            for extension, name in FILE_EXTENSIONS.items():
                if path.endswith(extension):
                    names.add(name)
        if any(p.endswith(".py") for p in paths) and source.find_files(
            "manage.py", max_results=1
        ):
            names.add("django")
        return sorted(names)

    if not isinstance(setting, list):
        logger.warning("prompt.language_blocks must be 'auto' or a list. Ignored.")
        return []
    names = []
    for name in setting:
        if name in LANGUAGE_BLOCKS:
            if name not in names:
                names.append(name)
        else:
            logger.warning(
                "Unknown language check '%s'. Known checks: %s.",
                name,
                ", ".join(LANGUAGE_BLOCKS),
            )
    return names


def render_project_rules(config) -> str:
    """Return the project rules text, or an empty string if there are none.

    The template has blocks that a blank line separates. A block with an
    empty value is left out.
    """
    rules = collect_rules(config)
    values = {
        "critical_rules": rules["critical"],
        "warning_rules": rules["warnings"],
        "suggestion_rules": rules["suggestions"],
        "additional_instructions": rules["additional"].strip(),
    }
    blocks = []
    for block in load_prompt("agent_project_rules").split("\n\n"):
        names = re.findall(r"\{(\w+)\}", block)
        if all(values.get(name) for name in names):
            blocks.append(render(block, **values))
    return "\n\n".join(blocks)


def build_system_prompt(config, parsed_files, source, step_target: int) -> str:
    """Return the system prompt with the language checks and project rules."""
    parts = [
        load_prompt(f"agent_lang_{name}")
        for name in detect_language_blocks(config, parsed_files, source)
    ]
    project_rules = render_project_rules(config)
    if project_rules:
        parts.append(project_rules)

    text = render(
        load_prompt("agent_system"),
        project_context="\n\n".join(parts),
        step_target=step_target,
    )
    return re.sub(r"\n{3,}", "\n\n", text)  # No blank block if parts is empty.


def build_task_message(config, tools) -> str:
    """Return the first user message: the changed files and some of their diffs.

    The message holds the diffs of as many files as fit in agent.inline_diff_chars.
    The model reads the other diffs with get_diff. A diff in the message counts as
    given, so a get_diff call for it gets a short note.
    """
    left = int(config.get("agent.inline_diff_chars", 24000))
    shown, missing = [], []
    for item in tools.parsed_files:
        text = tools.parser.format_for_llm([item]).strip()
        if len(text) <= left:
            left -= len(text)
            shown.append(text)
            tools.mark_given("get_diff", {"path": item["path"]})
        else:
            missing.append(item["path"])

    sections = []
    if shown:
        sections.append(
            render(load_prompt("agent_diff_shown"), diffs="\n\n".join(shown)).rstrip()
        )
    if missing:
        sections.append(
            render(
                load_prompt("agent_diff_missing"),
                files="\n".join(f"- {p}" for p in missing),
            ).rstrip()
        )
    text = render(
        load_prompt("agent_task"),
        changed_files=tools.changed_files_summary(),
        diff_section="\n\n".join(sections),
    )
    return re.sub(r"\n{3,}", "\n\n", text)
