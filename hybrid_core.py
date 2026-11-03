"""
Hybrid review engine.

The classic engine reads the whole diff in one request and proposes candidate
problems. The agent then checks each candidate with the read-only tools and
keeps only the candidates that it confirms. The cost is bounded by the number
of candidates, not by the size of the change.
"""

import logging
import re

from agent_core import AgentReviewer
from agent_tools import AgentTools
from prompts import load_prompt, render
from review_core import ReviewResult

logger = logging.getLogger(__name__)


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def collect_candidates(
    result: ReviewResult, limit: int
) -> tuple[list[tuple[str, str]], int]:
    """Return ([(severity, text)], skipped) from a classic result.

    Critical issues come first, then warnings. Duplicates are removed.
    The list holds at most `limit` items. `skipped` counts the others.
    """
    seen: set[str] = set()
    items: list[tuple[str, str]] = []
    for severity, texts in (
        ("critical", result.critical_issues),
        ("warning", result.warnings),
    ):
        for text in texts:
            key = _key(text)
            if key and key not in seen:
                seen.add(key)
                items.append((severity, text))
    skipped = max(len(items) - limit, 0)
    return items[: max(limit, 0)], skipped


def render_candidates(items: list[tuple[str, str]]) -> str:
    return "\n".join(f"{i}. [{sev}] {text}" for i, (sev, text) in enumerate(items, 1))


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    seen = {_key(t) for t in first}
    merged = list(first)
    for text in second:
        if _key(text) not in seen:
            seen.add(_key(text))
            merged.append(text)
    return merged


class HybridReviewer:
    """Classic proposal, then agent verification."""

    def __init__(self, config, classic, agent: AgentReviewer):
        self.config = config
        self.classic = classic
        self.agent = agent
        self.outcome = "hybrid"  # "hybrid" or "hybrid->classic"

    def review(self, diff_content: str, tools: AgentTools) -> ReviewResult:
        cfg = self.config
        proposal = self.classic.review_diff(diff_content)
        if proposal.status != "success":
            return proposal  # The classic engine already degrades to static analysis.

        limit = int(cfg.get("hybrid.max_candidates", 10))
        candidates, skipped = collect_candidates(proposal, limit)
        info = {"candidates": len(candidates), "skipped": skipped}

        if not candidates:
            if cfg.get("hybrid.when_no_candidates", "accept") == "agent":
                result = self.agent.review(tools)
                info["full_agent"] = True
                return self._finish(
                    result, proposal, info, keep_classic=result.status != "success"
                )
            proposal.agent_stats = {"hybrid": {**info, "kept": 0}}
            return proposal

        steps = int(cfg.get("hybrid.base_steps", 3)) + int(
            cfg.get("hybrid.steps_per_candidate", 2)
        ) * len(candidates)
        first = render(
            load_prompt("hybrid_task"),
            changed_files=tools.changed_files_summary(),
            candidates=render_candidates(candidates),
        )
        verified = self.agent.review(
            tools,
            prompt_name="hybrid_system",
            first_message=first,
            step_target=steps,
        )
        return self._finish(
            verified, proposal, info, keep_classic=verified.status != "success"
        )

    def _finish(self, verified, proposal, info, keep_classic: bool) -> ReviewResult:
        stats = dict(verified.agent_stats or {})
        if keep_classic:
            # The verifier failed. The classic result is better than no result.
            self.outcome = "hybrid->classic"
            info["fallback"] = "classic"
            info["fallback_reason"] = str(verified.raw_response)
            proposal.agent_stats = {**stats, "hybrid": info}
            return proposal
        info["kept"] = len(verified.critical_issues) + len(verified.warnings)
        verified.suggestions = _merge_unique(verified.suggestions, proposal.suggestions)
        if not verified.code_suggestions:
            verified.code_suggestions = proposal.code_suggestions
        verified.agent_stats = {**stats, "hybrid": info}
        return verified
