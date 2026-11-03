"""
Hybrid review engine.

The classic engine reads the whole diff in one request and proposes candidate
problems. The agent then checks each candidate with the read-only tools and
keeps only the candidates that it confirms. The cost is bounded by the number
of candidates, not by the size of the change.
"""

import logging

from agent_core import AgentReviewer
from agent_tools import AgentTools
from prompts import load_prompt, render
from review_core import ReviewResult, normalize_text

logger = logging.getLogger(__name__)


# Notices of the classic engine. They tell how the review ran. They are not findings.
NOTICE_PREFIXES = (
    "Chunk ",
    "Truncated review",
    "Review skipped",
    "\u26a0\ufe0f Used backup model",
    "\U0001f534 LLM model unavailable",
)


def is_notice(text: str) -> bool:
    return text.startswith(NOTICE_PREFIXES)


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
            key = normalize_text(text)
            if key and key not in seen and not is_notice(text):
                seen.add(key)
                items.append((severity, text))
    limit = max(limit, 0)
    return items[:limit], items[limit:]


def render_candidates(items: list[tuple[str, str]]) -> str:
    return "\n".join(f"{i}. [{sev}] {text}" for i, (sev, text) in enumerate(items, 1))


def _merge_unique(first: list[str], second: list[str]) -> list[str]:
    seen = {normalize_text(t) for t in first}
    merged = list(first)
    for text in second:
        if normalize_text(text) not in seen:
            seen.add(normalize_text(text))
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
        info = {"candidates": len(candidates), "skipped": len(skipped)}
        # Notices and candidates over the limit go to the final result as they are.
        notices = [
            t for t in proposal.critical_issues + proposal.warnings if is_notice(t)
        ]
        unverified = [
            f"Not verified (candidate limit): [{severity}] {text}"
            for severity, text in skipped
        ]

        if not candidates:
            if cfg.get("hybrid.when_no_candidates", "accept") == "agent":
                result = self.agent.review(tools)
                info["full_agent"] = True
                return self._finish(
                    result,
                    proposal,
                    info,
                    keep_classic=result.status != "success",
                    notices=notices,
                    unverified=unverified,
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
            verified,
            proposal,
            info,
            keep_classic=verified.status != "success",
            notices=notices,
            unverified=unverified,
        )

    def _finish(
        self,
        verified,
        proposal,
        info,
        keep_classic: bool,
        notices: list[str],
        unverified: list[str],
    ) -> ReviewResult:
        stats = dict(verified.agent_stats or {})
        if keep_classic:
            # The verifier failed. The classic result is better than no result.
            self.outcome = "hybrid->classic"
            info["fallback"] = "classic"
            info["fallback_reason"] = str(verified.raw_response)
            proposal.agent_stats = {**stats, "hybrid": info}
            return proposal
        info["kept"] = len(verified.critical_issues) + len(verified.warnings)
        verified.warnings = notices + verified.warnings
        verified.suggestions = _merge_unique(
            verified.suggestions, proposal.suggestions + unverified
        )
        verified.fallback_used = proposal.fallback_used
        verified.chunks_reviewed = proposal.chunks_reviewed
        verified.total_chunks = proposal.total_chunks
        if not verified.code_suggestions:
            verified.code_suggestions = proposal.code_suggestions
        verified.agent_stats = {**stats, "hybrid": info}
        return verified
