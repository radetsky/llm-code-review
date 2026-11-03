"""
Agent loop for code review.

The model explores the repository through read-only tools (see agent_tools.py)
and finishes by calling ``submit_review``. The loop enforces step, token and
wall-clock budgets, forces a final ``submit_review`` when a budget runs out,
and validates findings against the diff before returning a ReviewResult.

Qwen/SGLang specifics handled here: ``<think>`` blocks in content,
``reasoning_content`` (traced, never sent back), sloppy JSON in tool
arguments, and several tool calls in one message (up to 4 run in order).
"""

import json
import re
import sys
import time
from typing import Any

import json5
from openai import OpenAI, OpenAIError

from agent_prompt import build_system_prompt, build_task_message
from agent_tools import DUPLICATE_PREFIX, AgentTools
from prompts import load_prompt, render
from review_core import CodeSuggestion, ReviewResult

SUBMIT_TOOL = "submit_review"
MAX_NUDGES = 2
MAX_CALLS_PER_STEP = 4
MAX_STALE_STEPS = 2  # Number of steps in a row that mostly repeat earlier calls.
BASE_STEP_TARGET = 4  # Steps for a change with no files.
STEPS_PER_FILE = 2  # More steps for each changed file.
SEVERITIES = {
    "critical": "critical",
    "warning": "warning",
    "warn": "warning",
    "suggestion": "suggestion",
    "suggest": "suggestion",
    "info": "suggestion",
}

SUBMIT_SPEC = {
    "type": "function",
    "function": {
        "name": SUBMIT_TOOL,
        "description": (
            "Send the final review. Call this tool one time, when you finish. "
            "If you find no problems, send an empty findings list."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "warning", "suggestion"],
                            },
                            "file": {"type": "string"},
                            "line": {
                                "type": "integer",
                                "description": "Line number in the new version of the file",
                            },
                            "line_end": {"type": "integer"},
                            "message": {"type": "string"},
                            "suggested_code": {
                                "type": "string",
                                "description": (
                                    "New code for the lines from line to line_end. "
                                    "Use it only with severity suggestion. Give code "
                                    "only, with no line numbers and no code fences."
                                ),
                            },
                        },
                        "required": ["severity", "file", "line", "message"],
                    },
                }
            },
            "required": ["findings"],
        },
    },
}

DEFAULT_SYSTEM_PROMPT = load_prompt("agent_system")

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
FENCE_RE = re.compile(r"^```[A-Za-z0-9_+-]*\s*\n(.*?)\n?```\s*$", re.DOTALL)
NUMBERED_RE = re.compile(r"^\s*(\d+): ?(.*)$")


def strip_think(text: str | None) -> str:
    """Remove Qwen ``<think>`` reasoning from visible content."""
    if not text:
        return ""
    text = THINK_RE.sub("", text)
    if "</think>" in text:  # opening tag was cut off by the server
        text = text.split("</think>")[-1]
    if "<think>" in text:  # reasoning was cut off mid-way
        text = text.split("<think>")[0]
    return text.strip()


def parse_arguments(raw: Any) -> tuple[dict | None, str | None]:
    """Parse tool-call arguments tolerantly. Returns (args, error)."""
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    if not isinstance(raw, str):
        return None, "arguments must be a JSON object"
    text = raw.strip()
    fence = FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            value = json5.loads(text)  # trailing commas, single quotes, comments
        except (ValueError, RecursionError):
            return None, "arguments are not valid JSON"
    if not isinstance(value, dict):
        return None, "arguments must be a JSON object"
    return value, None


def clean_suggested_code(code: str, line_start: int) -> str:
    """Remove fences and copied line-number prefixes from suggested code."""
    code = code.replace("\r\n", "\n").strip("\n")
    fence = FENCE_RE.match(code.strip())
    if fence:
        code = fence.group(1)
    lines = code.split("\n")
    parsed = [NUMBERED_RE.match(line) for line in lines]
    if lines and all(
        m and int(m.group(1)) == line_start + i for i, m in enumerate(parsed)
    ):
        lines = [m.group(2) for m in parsed]
    return "\n".join(lines).rstrip("\n")


def valid_lines_by_file(parsed_files: list[dict]) -> dict[str, set[int]]:
    """New-file line numbers visible in the diff (added and context lines)."""
    result: dict[str, set[int]] = {}
    for f in parsed_files:
        lines = result.setdefault(f["path"], set())
        for hunk in f["hunks"]:
            for key in ("added_lines", "context_before", "context_after"):
                lines.update(entry["line"] for entry in hunk[key])
    return result


class AgentReviewer:
    """Runs the tool-calling review loop."""

    def __init__(
        self, config, client=None, trace: bool = False, trace_llm: bool = False
    ):
        self.config = config
        self.client = client
        self.trace = trace
        self.trace_llm = trace_llm
        self._printed = 0  # messages already shown by trace_llm

    # -- setup -------------------------------------------------------------

    def _get_client(self):
        if self.client is None:
            api_key = self.config.get_api_key()
            if not api_key:
                raise ValueError(
                    "API key not found. Set LLM_API_KEY environment variable."
                )
            self.client = OpenAI(
                base_url=self.config.get_base_url(),
                api_key=api_key,
                timeout=self.config.get_timeout(),
            )
        return self.client

    # -- tracing -----------------------------------------------------------

    def _trace(self, message: str) -> None:
        if self.trace:
            print(f"[TRACE] {message}", file=sys.stderr)

    def _trace_request(self, kwargs: dict, messages: list[dict]) -> None:
        if not self.trace_llm:
            return
        params = {k: v for k, v in kwargs.items() if k not in ("messages", "tools")}
        tool_names = [t["function"]["name"] for t in kwargs.get("tools", [])]
        new = messages[self._printed :]
        print("----- LLM REQUEST BEGIN -----", file=sys.stderr)
        print(f"params={json.dumps(params, default=str)}", file=sys.stderr)
        print(f"tools={tool_names}", file=sys.stderr)
        print(
            f"messages: {len(messages)} total, showing {len(new)} new "
            f"(earlier ones were printed by previous requests)",
            file=sys.stderr,
        )
        for m in new:
            print(json.dumps(m, ensure_ascii=False, indent=2), file=sys.stderr)
        print("----- LLM REQUEST END -----", file=sys.stderr)
        self._printed = len(messages)

    def _trace_response(self, message: Any, usage_tokens: int | None) -> None:
        if not self.trace_llm:
            return
        reasoning = getattr(message, "reasoning_content", None)
        calls = [
            {
                "id": getattr(c, "id", None),
                "name": c.function.name,
                "arguments": c.function.arguments,
            }
            for c in (getattr(message, "tool_calls", None) or [])
        ]
        print("----- LLM RESPONSE BEGIN -----", file=sys.stderr)
        print(f"total_tokens={usage_tokens}", file=sys.stderr)
        if reasoning:
            print(f"reasoning_content:\n{reasoning}", file=sys.stderr)
        print(f"content:\n{getattr(message, 'content', None)}", file=sys.stderr)
        print(f"tool_calls: {json.dumps(calls, ensure_ascii=False)}", file=sys.stderr)
        print("----- LLM RESPONSE END -----", file=sys.stderr)

    # -- LLM call ----------------------------------------------------------

    @staticmethod
    def _is_retryable(error: OpenAIError) -> bool:
        status = getattr(error, "status_code", None)
        return status is None or status == 429 or status >= 500

    def _chat(
        self, messages: list[dict], tools: list[dict], tool_choice: Any, timeout: float
    ):
        """One chat completion with retry on transient errors."""
        kwargs: dict[str, Any] = {
            "model": self.config.get_model(),
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": 0.1,
            "timeout": timeout,
        }
        extra = self.config.get_extra_body()
        if extra:
            kwargs["extra_body"] = extra
        self._trace_request(kwargs, messages)

        retries = int(self.config.get("llm.max_retries", 3))
        for attempt in range(retries + 1):
            try:
                return self._get_client().chat.completions.create(**kwargs)
            except OpenAIError as e:
                if attempt >= retries or not self._is_retryable(e):
                    raise
                delay = min(2**attempt, 10)
                self._trace(
                    f"LLM call failed ({e}); retry {attempt + 1}/{retries} in {delay}s"
                )
                time.sleep(delay)

    def _tokens_used(self, response: Any, messages: list[dict], message: Any) -> int:
        usage = getattr(response, "usage", None)
        total = getattr(usage, "total_tokens", None) if usage else None
        if isinstance(total, int):
            return total
        chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
        chars += len(getattr(message, "content", None) or "")
        return chars // max(int(self.config.get("llm.chars_per_token", 4)), 1)

    # -- main loop ---------------------------------------------------------

    def review(self, tools: AgentTools) -> ReviewResult:
        """Run the agent. Never raises for model/transport failures."""
        cfg = self.config
        max_steps = int(cfg.get("agent.max_steps", 20))
        max_tokens = int(cfg.get("agent.max_total_tokens", 1000000))
        wall = float(cfg.get("agent.wall_timeout_sec", 300))
        started = time.monotonic()
        self._printed = 0

        stats = {
            "steps": 0,
            "tokens": 0,
            "tool_calls": 0,
            "invalid_tool_calls": 0,
            "ignored_tool_calls": 0,
            "duplicate_tool_calls": 0,
            "forced_submit": None,
            "dropped_findings": 0,
            "duration_sec": 0.0,
            "stop_reason": None,
        }
        specs = tools.specs + [SUBMIT_SPEC]
        # The step target grows with the size of the change, but it stays below max_steps.
        step_target = min(
            max(max_steps - 2, 1),
            BASE_STEP_TARGET + STEPS_PER_FILE * len(tools.parsed_files),
        )
        # The step cap is close to the step target. A change that needs more
        # steps can still use max_steps, but only through a larger steps_over_target.
        max_steps = min(
            max_steps, step_target + int(cfg.get("agent.steps_over_target", 100))
        )
        stats["step_target"] = step_target
        stats["step_cap"] = max_steps
        system_prompt = build_system_prompt(
            cfg, tools.parsed_files, tools.source, step_target
        )
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_task_message(cfg, tools)},
        ]
        nudges = 0
        stale_steps = 0

        def finish(result: ReviewResult) -> ReviewResult:
            stats["duration_sec"] = round(time.monotonic() - started, 2)
            result.agent_stats = stats
            self._trace(f"Agent done: {json.dumps(stats)}")
            return result

        def remaining() -> float:
            return max(wall - (time.monotonic() - started), 1.0)

        try:
            while True:
                reason = None
                if stats["steps"] >= max_steps:
                    reason = "max_steps"
                elif stats["tokens"] >= max_tokens:
                    reason = "max_total_tokens"
                elif time.monotonic() - started >= wall:
                    reason = "wall_timeout"
                elif nudges > MAX_NUDGES:
                    reason = "no_tool_calls"
                elif stale_steps >= MAX_STALE_STEPS:
                    reason = "repeated_calls"
                if reason:
                    return finish(
                        self._force_submit(
                            tools, messages, specs, stats, reason, remaining
                        )
                    )

                stats["steps"] += 1
                response = self._chat(messages, specs, "auto", remaining())
                message = self._message(response)
                stats["tokens"] += self._tokens_used(response, messages, message)
                self._trace_response(message, stats["tokens"])

                content = strip_think(getattr(message, "content", None))
                calls = getattr(message, "tool_calls", None) or []
                if not calls:
                    nudges += 1
                    self._trace(f"step {stats['steps']}: no tool call (nudge {nudges})")
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {
                            "role": "user",
                            "content": load_prompt("agent_nudge"),
                        }
                    )
                    continue

                batch, ignored = self._select_calls(calls, stats["steps"])
                stats["ignored_tool_calls"] += ignored
                if ignored:
                    self._trace(
                        f"step {stats['steps']}: ignoring {ignored} tool call(s) "
                        f"(limit {MAX_CALLS_PER_STEP} per message; submit_review "
                        "ends the review and is run alone)"
                    )
                messages.append(self._assistant_message(content, batch))

                outputs: list[str] = []
                for index, (call_id, name, args, error, raw) in enumerate(batch, 1):
                    if name == SUBMIT_TOOL:
                        result, problem = self._build_result(args, error, tools, stats)
                        if result is not None:
                            stats["stop_reason"] = "submitted"
                            self._trace(
                                f"step {stats['steps']}: submit_review accepted"
                            )
                            return finish(result)
                        stats["invalid_tool_calls"] += 1
                        output = f"Error: {problem}"
                    elif error:
                        stats["invalid_tool_calls"] += 1
                        output = f"Error: {error}"
                    else:
                        output = tools.call(name, args)
                        if output.startswith("Error: unknown tool"):
                            stats["invalid_tool_calls"] += 1
                        else:
                            stats["tool_calls"] += 1

                    shown = (
                        json.dumps(args, ensure_ascii=False)
                        if args is not None
                        else raw
                    )
                    self._trace(
                        f"step {stats['steps']}/{max_steps} [{index}/{len(batch)}]: "
                        f"{name}({shown}) -> {len(output)} chars | "
                        f"tokens used: {stats['tokens']}"
                    )
                    outputs.append(output)
                    if output.startswith(DUPLICATE_PREFIX):
                        stats["duplicate_tool_calls"] += 1

                repeats = sum(o.startswith(DUPLICATE_PREFIX) for o in outputs)
                is_stale = repeats * 2 > len(outputs)  # More than half are repeats.
                stale_steps = stale_steps + 1 if is_stale else 0
                if ignored:
                    outputs[-1] += (
                        f"\n[{ignored} tool call(s) did not run. The limit is "
                        f"{MAX_CALLS_PER_STEP} calls for each message. Send them again "
                        "in your next message if you need them.]"
                    )
                for (call_id, *_), output in zip(batch, outputs):
                    messages.append(
                        {"role": "tool", "tool_call_id": call_id, "content": output}
                    )
        except OpenAIError as e:
            stats["stop_reason"] = "model_unavailable"
            self._trace(f"LLM error: {e}")
            return finish(self._failed("model_unavailable", f"LLM request failed: {e}"))
        except ValueError as e:  # e.g. missing API key
            stats["stop_reason"] = "error"
            return finish(self._failed("error", str(e)))

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _message(response: Any) -> Any:
        if hasattr(response, "choices") and response.choices:
            return response.choices[0].message
        raise ValueError(
            f"Unexpected response type from LLM API: {type(response).__name__}"
        )

    @staticmethod
    def _select_calls(calls: list, step: int) -> tuple[list[tuple], int]:
        """Pick the tool calls to run from one model message.

        Returns ([(id, name, args, error, raw_arguments)], ignored_count).
        submit_review ends the review, so when present it is run alone.
        Ids are made unique; missing ids are generated.
        """
        parsed = []
        seen: set[str] = set()
        for index, call in enumerate(calls):
            call_id = getattr(call, "id", None)
            if not call_id or call_id in seen:
                call_id = f"call_{step}_{index}"
            seen.add(call_id)
            raw = call.function.arguments
            args, error = parse_arguments(raw)
            parsed.append((call_id, call.function.name, args, error, raw))

        for entry in parsed:
            if entry[1] == SUBMIT_TOOL:
                return [entry], len(parsed) - 1
        return parsed[:MAX_CALLS_PER_STEP], max(len(parsed) - MAX_CALLS_PER_STEP, 0)

    @staticmethod
    def _assistant_message(content: str, batch: list[tuple]) -> dict:
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args if args is not None else {}),
                    },
                }
                for call_id, name, args, _error, _raw in batch
            ],
        }

    @staticmethod
    def _failed(status: str, reason: str) -> ReviewResult:
        return ReviewResult(
            status=status,
            critical_issues=[],
            warnings=[],
            suggestions=[],
            raw_response=reason,
        )

    def _force_submit(
        self, tools, messages, specs, stats, reason, remaining
    ) -> ReviewResult:
        """Ask for the final review when a budget is exhausted."""
        stats["forced_submit"] = reason
        stats["stop_reason"] = f"forced:{reason}"
        self._trace(f"Budget exhausted ({reason}); forcing submit_review")
        messages.append(
            {
                "role": "user",
                "content": render(load_prompt("agent_budget_exhausted"), reason=reason),
            }
        )
        forced = {"type": "function", "function": {"name": SUBMIT_TOOL}}
        response = self._chat(messages, [SUBMIT_SPEC], forced, remaining())
        message = self._message(response)
        stats["tokens"] += self._tokens_used(response, messages, message)
        self._trace_response(message, stats["tokens"])
        calls = getattr(message, "tool_calls", None) or []
        if not calls or calls[0].function.name != SUBMIT_TOOL:
            return self._failed("error", f"Model did not submit a review ({reason})")
        args, error = parse_arguments(calls[0].function.arguments)
        result, problem = self._build_result(args, error, tools, stats)
        if result is None:
            return self._failed("error", f"Forced submit_review was invalid: {problem}")
        return result

    def _build_result(
        self, args, error, tools, stats
    ) -> tuple[ReviewResult | None, str | None]:
        """Validate submit_review arguments and convert them to a ReviewResult."""
        if error:
            return None, error
        findings = args.get("findings")
        if findings is None:
            findings = []
        if not isinstance(findings, list):
            return None, "'findings' must be a list"

        valid = valid_lines_by_file(tools.parsed_files)
        allow_code = self.config.get_code_suggestions_enabled()
        critical: list[str] = []
        warnings: list[str] = []
        suggestions: list[str] = []
        code_suggestions: list[CodeSuggestion] = []
        seen: set[tuple] = set()

        for item in findings:
            parsed = self._check_finding(item, valid)
            if parsed is None:
                stats["dropped_findings"] += 1
                self._trace(f"Dropped finding not anchored in the diff: {item!r}")
                continue
            severity, path, line, line_end, message, code = parsed
            key = (path, line, " ".join(message.lower().split()))
            if key in seen:
                stats["dropped_findings"] += 1
                continue
            seen.add(key)

            text = f"{path}:{line}: {message}"
            if severity == "critical":
                critical.append(text)
            elif severity == "warning":
                warnings.append(text)
            elif code is not None and allow_code:
                code_suggestions.append(
                    CodeSuggestion(
                        file=path,
                        line_start=line,
                        line_end=line_end,
                        description=message,
                        suggested_code=clean_suggested_code(code, line),
                    )
                )
            else:
                suggestions.append(text)

        return (
            ReviewResult(
                status="success",
                critical_issues=critical,
                warnings=warnings,
                suggestions=suggestions,
                raw_response=json.dumps(args, ensure_ascii=False),
                code_suggestions=code_suggestions,
            ),
            None,
        )

    @staticmethod
    def _check_finding(item: Any, valid: dict[str, set[int]]):
        """Return a normalized tuple, or None if the finding is unusable."""
        if not isinstance(item, dict):
            return None
        severity = SEVERITIES.get(str(item.get("severity", "")).strip().lower())
        path = item.get("file")
        message = item.get("message")
        if not severity or not isinstance(path, str) or not isinstance(message, str):
            return None
        message = message.strip()
        path = path.strip().removeprefix("./")
        try:
            line = int(item.get("line"))
        except (TypeError, ValueError):
            return None
        if not message or path not in valid or line not in valid[path]:
            return None
        try:
            line_end = int(item.get("line_end") or line)
        except (TypeError, ValueError):
            line_end = line
        if line_end < line or not all(
            n in valid[path] for n in range(line, line_end + 1)
        ):
            line_end = line
        code = item.get("suggested_code")
        if severity != "suggestion" or not isinstance(code, str) or not code.strip():
            code = None
        return severity, path, line, line_end, message, code
