"""Tests for the hybrid engine: classic proposes, the agent verifies."""

import httpx
import openai

from agent_core import AgentReviewer
from hybrid_core import HybridReviewer, collect_candidates, render_candidates
from review_core import CodeSuggestion, ReviewResult
from test_agent_core import FakeClient, finding, submit, tools  # noqa: F401


def classic_result(critical=(), warnings=(), suggestions=(), status="success"):
    return ReviewResult(
        status=status,
        critical_issues=list(critical),
        warnings=list(warnings),
        suggestions=list(suggestions),
        raw_response="boom" if status != "success" else None,
    )


class FakeClassic:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def review_diff(self, diff):
        self.calls += 1
        return self.result


def make(tools, classic, script):
    client = FakeClient(script)
    agent = AgentReviewer(tools.config, client=client)
    return HybridReviewer(tools.config, FakeClassic(classic), agent), client


class TestCandidates:
    def test_order_dedupe_and_cap(self):
        r = classic_result(
            critical=["a.py:1: Bad"],
            warnings=["a.py:2: Risky", "A.py:2:  risky", "b.py:3: Odd"],
        )
        items, skipped = collect_candidates(r, 2)
        assert items == [("critical", "a.py:1: Bad"), ("warning", "a.py:2: Risky")]
        assert skipped == [("warning", "b.py:3: Odd")]

    def test_render(self):
        assert render_candidates([("critical", "x"), ("warning", "y")]) == (
            "1. [critical] x\n2. [warning] y"
        )


class TestHybrid:
    def test_non_success_returned_without_agent(self, tools):
        h, client = make(tools, classic_result(status="model_unavailable"), [])
        result = h.review("diff", tools)
        assert result.status == "model_unavailable"
        assert client.requests == []

    def test_no_candidates_accepts_classic(self, tools):
        h, client = make(tools, classic_result(suggestions=["s"]), [])
        result = h.review("diff", tools)
        assert result.suggestions == ["s"]
        assert client.requests == []
        assert result.agent_stats["hybrid"]["candidates"] == 0

    def test_no_candidates_can_run_full_agent(self, tools):
        tools.config.config["hybrid"]["when_no_candidates"] = "agent"
        h, client = make(tools, classic_result(), [submit([finding()])])
        result = h.review("diff", tools)
        assert len(client.requests) == 1
        assert result.warnings == ["app.py:2: Problem"]
        assert result.agent_stats["hybrid"]["full_agent"] is True

    def test_verifier_keeps_only_confirmed(self, tools):
        classic = classic_result(
            warnings=["app.py:2: Problem", "app.py:6: Other"],
            suggestions=["Use types"],
        )
        h, client = make(tools, classic, [submit([finding()])])
        result = h.review("diff", tools)
        assert result.warnings == ["app.py:2: Problem"]
        assert result.suggestions == ["Use types"]
        assert h.outcome == "hybrid"
        stats = result.agent_stats["hybrid"]
        assert stats["candidates"] == 2 and stats["kept"] == 1
        first = client.requests[0]["messages"]
        assert "hybrid reviewer" not in first[0]["content"]
        assert "1. [warning] app.py:2: Problem" in first[1]["content"]
        assert "2. [warning] app.py:6: Other" in first[1]["content"]

    def test_step_target_depends_on_candidates(self, tools):
        classic = classic_result(warnings=["app.py:2: A", "app.py:6: B"])
        h, _ = make(tools, classic, [submit([])])
        result = h.review("diff", tools)
        assert result.agent_stats["step_target"] == 7

    def test_verifier_failure_falls_back_to_classic(self, tools):
        classic = classic_result(warnings=["app.py:2: Problem"])
        h, _ = make(
            tools,
            classic,
            [
                openai.APIStatusError(
                    "boom",
                    response=httpx.Response(
                        400, request=httpx.Request("POST", "http://x")
                    ),
                    body=None,
                )
            ],
        )
        result = h.review("diff", tools)
        assert result.warnings == ["app.py:2: Problem"]
        assert h.outcome == "hybrid->classic"
        assert result.agent_stats["hybrid"]["fallback"] == "classic"

    def test_code_suggestions_kept_from_classic(self, tools):
        classic = classic_result(warnings=["app.py:2: Problem"])
        classic.code_suggestions = [
            CodeSuggestion(
                file="app.py",
                line_start=2,
                line_end=2,
                description="d",
                suggested_code="x",
            )
        ]
        h, _ = make(tools, classic, [submit([])])
        result = h.review("diff", tools)
        assert result.code_suggestions == classic.code_suggestions


class TestNoticesAndLimit:
    def test_notices_are_not_candidates(self):
        r = classic_result(
            warnings=[
                "Chunk 2/3 review failed: x",
                "Truncated review: 1 file(s) skipped",
                "a.py:2: Risky",
            ]
        )
        items, skipped = collect_candidates(r, 5)
        assert items == [("warning", "a.py:2: Risky")] and skipped == []

    def test_notices_and_coverage_reach_the_result(self, tools):
        classic = classic_result(
            warnings=["Chunk 2/3 review failed: x", "app.py:2: Problem"]
        )
        classic.chunks_reviewed, classic.total_chunks = 2, 3
        classic.fallback_used = True
        h, client = make(tools, classic, [submit([])])
        result = h.review("diff", tools)
        assert result.warnings == ["Chunk 2/3 review failed: x"]
        assert (result.chunks_reviewed, result.total_chunks) == (2, 3)
        assert result.fallback_used is True
        assert "Chunk 2/3" not in client.requests[0]["messages"][1]["content"]

    def test_skipped_candidates_are_reported(self, tools):
        tools.config.config["hybrid"]["max_candidates"] = 1
        classic = classic_result(warnings=["app.py:2: A", "app.py:6: B"])
        h, _ = make(tools, classic, [submit([])])
        result = h.review("diff", tools)
        assert result.suggestions == [
            "Not verified (candidate limit): [warning] app.py:6: B"
        ]
        assert result.agent_stats["hybrid"]["skipped"] == 1
