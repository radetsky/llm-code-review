"""
Core LLM integration for code review system.
Based on existing hello_llm.py structure.
"""

import time
import random
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass

from openai import OpenAI, OpenAIError


@dataclass
class ReviewResult:
    """Result of LLM code review."""

    status: str  # "success", "model_unavailable", "error", "skipped" - technical status of LLM operation
    critical_issues: List[str]
    warnings: List[str]
    suggestions: List[str]
    fallback_used: bool = False
    raw_response: Optional[str] = None
    chunks_reviewed: int = 0
    total_chunks: int = 0

    @property
    def review_outcome(self) -> str:
        """Code review outcome based on findings: critical, warnings, or success."""
        if self.critical_issues:
            return "critical"
        elif self.warnings:
            return "warnings"
        return "success"


class LLMReviewer:
    """Handles LLM interactions for code review."""

    DEFAULT_PROMPT = """You are a security-focused code reviewer. Analyze the following git diff changes for:

CRITICAL ISSUES (block commit):
- Hardcoded credentials, API keys, secrets
- SQL injection, XSS vulnerabilities
- Unsafe functions (eval(), exec(), system())
- Direct file system operations without validation
- Network requests to external endpoints without proper validation
- Buffer overflow risks
- Command injection vulnerabilities
{custom_critical_rules}

WARNINGS (allow commit but flag):
- Code style violations
- Potential bugs and edge cases
- Performance issues
- Missing error handling
- Input validation gaps
- Documentation gaps
{custom_warnings}

SUGGESTIONS (improvements):
- Best practices recommendations
- Code organization improvements
- Security enhancements
{custom_suggestions}

{additional_instructions}

Format your response as:
CRITICAL: [issue description]
WARNING: [issue description]
SUGGESTION: [suggestion]

If no issues found for a category, respond "NONE".

Changes to review:
{diff_content}

Focus on security vulnerabilities first, then code quality."""

    def __init__(self, config, trace: bool = False, trace_llm: bool = False):
        self.config = config
        self.client = None
        self.trace = trace
        self.trace_llm = trace_llm
        self._setup_logging()

    def _build_prompt(self, diff_content: str) -> str:
        """Build review prompt from config or use default."""
        prompt_config = self.config.get("prompt") or {}
        if not isinstance(prompt_config, dict):
            prompt_config = {}

        # Build placeholder strings first (needed for both custom and default prompts)
        custom_critical = prompt_config.get("custom_critical_rules") or []
        custom_warnings = prompt_config.get("custom_warnings") or []
        custom_suggestions = prompt_config.get("custom_suggestions") or []
        additional = prompt_config.get("additional_instructions") or ""

        if not isinstance(custom_critical, list):
            custom_critical = []
        if not isinstance(custom_warnings, list):
            custom_warnings = []
        if not isinstance(custom_suggestions, list):
            custom_suggestions = []
        if not isinstance(additional, str):
            additional = ""

        critical_str = "\n".join(
            f"- {rule}" for rule in custom_critical if isinstance(rule, str)
        )
        warnings_str = "\n".join(
            f"- {rule}" for rule in custom_warnings if isinstance(rule, str)
        )
        suggestions_str = "\n".join(
            f"- {rule}" for rule in custom_suggestions if isinstance(rule, str)
        )

        # Check for custom prompt - pass all placeholders
        custom_prompt = prompt_config.get("custom_prompt")
        if custom_prompt and isinstance(custom_prompt, str):
            try:
                return custom_prompt.format(
                    diff_content=diff_content,
                    custom_critical_rules=critical_str,
                    custom_warnings=warnings_str,
                    custom_suggestions=suggestions_str,
                    additional_instructions=additional,
                )
            except KeyError as e:
                self.logger.warning(
                    f"Custom prompt has invalid placeholder: {e}. Using default."
                )

        try:
            return self.DEFAULT_PROMPT.format(
                diff_content=diff_content,
                custom_critical_rules=critical_str,
                custom_warnings=warnings_str,
                custom_suggestions=suggestions_str,
                additional_instructions=additional,
            )
        except KeyError as e:
            self.logger.error(f"Prompt template error: {e}. Using minimal prompt.")
            return f"Review this code diff for security issues:\n\n{diff_content}"

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count from character count."""
        chars_per_token = self.config.get_chars_per_token()
        return len(text) // chars_per_token

    def _check_token_limit(self, prompt: str) -> Tuple[bool, int, int]:
        """Check if prompt exceeds token limit.

        Returns:
            Tuple of (exceeds_limit, estimated_tokens, max_tokens)
        """
        max_tokens = self.config.get_max_tokens()
        estimated_tokens = self._estimate_tokens(prompt)
        exceeds = estimated_tokens > max_tokens
        if exceeds:
            self.logger.warning(
                f"Prompt exceeds token limit: ~{estimated_tokens} tokens (limit: {max_tokens})"
            )
        return (exceeds, estimated_tokens, max_tokens)

    def _truncate_diff(
        self, diff_content: str, max_chars: int
    ) -> Tuple[str, List[str]]:
        """Truncate diff at file boundaries to fit within character limit.

        Returns:
            Tuple of (truncated_diff, list of skipped files)
        """
        lines = diff_content.split("\n")
        result_lines = []
        current_size = 0
        skipped_files = []
        current_file = None
        file_start_idx = 0

        for i, line in enumerate(lines):
            if line.startswith("diff --git") or line.startswith("File:"):
                if current_file and current_size > max_chars:
                    result_lines = result_lines[:file_start_idx]
                    skipped_files.append(current_file)
                current_file = line
                file_start_idx = len(result_lines)

            line_size = len(line) + 1
            if current_size + line_size <= max_chars:
                result_lines.append(line)
                current_size += line_size
            elif not skipped_files or current_file not in skipped_files:
                if current_file:
                    skipped_files.append(current_file)

        return ("\n".join(result_lines), skipped_files)

    def _chunk_diff(self, diff_content: str, max_chars: int) -> List[str]:
        """Split diff into chunks at file boundaries.

        Each chunk will contain complete files and fit within the character limit.
        """
        chunks = []
        current_chunk_lines = []
        current_chunk_size = 0
        current_file_lines = []
        current_file_size = 0

        lines = diff_content.split("\n")

        for line in lines:
            is_file_boundary = line.startswith("diff --git") or line.startswith("File:")

            if is_file_boundary and current_file_lines:
                if current_chunk_size + current_file_size <= max_chars:
                    current_chunk_lines.extend(current_file_lines)
                    current_chunk_size += current_file_size
                else:
                    if current_chunk_lines:
                        chunks.append("\n".join(current_chunk_lines))
                    current_chunk_lines = current_file_lines.copy()
                    current_chunk_size = current_file_size

                current_file_lines = []
                current_file_size = 0

            current_file_lines.append(line)
            current_file_size += len(line) + 1

        if current_file_lines:
            if current_chunk_size + current_file_size <= max_chars:
                current_chunk_lines.extend(current_file_lines)
            else:
                if current_chunk_lines:
                    chunks.append("\n".join(current_chunk_lines))
                current_chunk_lines = current_file_lines

        if current_chunk_lines:
            chunks.append("\n".join(current_chunk_lines))

        return chunks if chunks else [diff_content]

    def _handle_token_limit_exceeded(
        self, diff_content: str, estimated_tokens: int, max_tokens: int
    ) -> ReviewResult:
        """Handle case when token limit is exceeded based on configured strategy."""
        strategy = self.config.get_token_limit_strategy()
        chars_per_token = self.config.get_chars_per_token()
        max_diff_chars = max_tokens * chars_per_token

        prompt_overhead = len(self._build_prompt(""))
        available_diff_chars = max_diff_chars - prompt_overhead

        self.logger.info(f"Token limit exceeded. Using strategy: {strategy}")

        if strategy == "skip":
            return ReviewResult(
                status="skipped",
                critical_issues=[],
                warnings=[
                    f"Review skipped: diff too large (~{estimated_tokens} tokens, limit: {max_tokens})"
                ],
                suggestions=[
                    "Consider reviewing smaller changesets or increasing max_tokens_per_request"
                ],
            )

        elif strategy == "truncate":
            truncated_diff, skipped_files = self._truncate_diff(
                diff_content, available_diff_chars
            )

            if not truncated_diff.strip():
                return ReviewResult(
                    status="skipped",
                    critical_issues=[],
                    warnings=[
                        "Review skipped: could not fit any complete files within token limit"
                    ],
                    suggestions=[],
                )

            result = self._call_llm(truncated_diff)
            if skipped_files:
                result.warnings.append(
                    f"Truncated review: {len(skipped_files)} file(s) skipped due to size limit"
                )
            return result

        else:  # chunk strategy (default)
            return self._review_chunks(diff_content, available_diff_chars)

    def _review_chunks(
        self, diff_content: str, max_chars_per_chunk: int
    ) -> ReviewResult:
        """Review diff in multiple chunks and aggregate results."""
        chunks = self._chunk_diff(diff_content, max_chars_per_chunk)
        total_chunks = len(chunks)

        self.logger.info(f"Splitting diff into {total_chunks} chunks for review")
        self._trace_print(f"Chunking: splitting diff into {total_chunks} chunks")

        all_critical = []
        all_warnings = []
        all_suggestions = []
        chunks_reviewed = 0
        raw_responses = []

        for i, chunk in enumerate(chunks):
            self.logger.info(f"Reviewing chunk {i + 1}/{total_chunks}")
            self._trace_print(f"Chunking: reviewing chunk {i + 1}/{total_chunks}")
            try:
                result = self._call_llm(chunk)
                all_critical.extend(result.critical_issues)
                all_warnings.extend(result.warnings)
                all_suggestions.extend(result.suggestions)
                chunks_reviewed += 1
                if result.raw_response:
                    raw_responses.append(
                        f"--- Chunk {i + 1} ---\n{result.raw_response}"
                    )
            except Exception as e:
                self.logger.warning(f"Failed to review chunk {i + 1}: {e}")
                all_warnings.append(
                    f"Chunk {i + 1}/{total_chunks} review failed: {str(e)}"
                )

        unique_critical = list(dict.fromkeys(all_critical))
        unique_warnings = list(dict.fromkeys(all_warnings))
        unique_suggestions = list(dict.fromkeys(all_suggestions))

        status = "success" if chunks_reviewed > 0 else "error"

        return ReviewResult(
            status=status,
            critical_issues=unique_critical,
            warnings=unique_warnings,
            suggestions=unique_suggestions,
            raw_response="\n\n".join(raw_responses) if raw_responses else None,
            chunks_reviewed=chunks_reviewed,
            total_chunks=total_chunks,
        )

    def _setup_logging(self):
        """Setup logging configuration."""
        logging.basicConfig(
            format="%(asctime)s [%(levelname)s] %(message)s",
            level=logging.INFO,
        )
        self.logger = logging.getLogger(__name__)

    def _get_client(self) -> OpenAI:
        """Get configured OpenAI client."""
        if self.client is None:
            api_key = self.config.get_api_key()
            if not api_key:
                raise ValueError(
                    "API key not found. Set LLM_API_KEY environment variable."
                )

            base_url = self.config.get_base_url()
            timeout = self.config.get_timeout()

            self.client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

        return self.client

    def review_diff(self, diff_content: str) -> ReviewResult:
        """Review code diff using LLM with retry and fallback."""
        if not diff_content.strip() or diff_content == "No code changes to review.":
            return ReviewResult(
                status="success", critical_issues=[], warnings=[], suggestions=[]
            )

        prompt = self._build_prompt(diff_content)
        exceeds_limit, estimated_tokens, max_tokens = self._check_token_limit(prompt)

        if exceeds_limit:
            return self._handle_token_limit_exceeded(
                diff_content, estimated_tokens, max_tokens
            )

        max_retries = self.config.get("llm.max_retries", 3)

        for attempt in range(max_retries):
            try:
                return self._call_llm(diff_content)
            except OpenAIError as e:
                self.logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/{max_retries}): {e}"
                )

                if self._is_retryable_error(e) and attempt < max_retries - 1:
                    wait_time = self._calculate_backoff(attempt)
                    self.logger.info(f"Retrying in {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    return self._handle_model_unavailable(diff_content, e)
            except Exception as e:
                self.logger.error(f"Unexpected error during LLM review: {e}")
                return ReviewResult(
                    status="error",
                    critical_issues=[f"Review system error: {str(e)}"],
                    warnings=[],
                    suggestions=[],
                )

        # Fallback in case all retries fail
        return ReviewResult(
            status="error",
            critical_issues=["All retry attempts failed"],
            warnings=[],
            suggestions=[],
        )

    def _trace_print(self, message: str):
        """Print trace message to stderr if trace mode is enabled."""
        if self.trace:
            import sys

            print(f"[TRACE] {message}", file=sys.stderr)

    def _trace_llm_request(self, prompt: str, model: str, base_url: str):
        """Output full LLM request when LLM tracing is enabled."""
        if not self.trace_llm:
            return

        import sys

        print("----- LLM REQUEST BEGIN -----", file=sys.stderr)
        print(f"model={model} base_url={base_url}", file=sys.stderr)
        print(prompt, file=sys.stderr)
        print("----- LLM REQUEST END -----", file=sys.stderr)

    def _trace_llm_response(self, response: str):
        """Output full LLM response when LLM tracing is enabled."""
        if not self.trace_llm:
            return

        import sys

        print("----- LLM RESPONSE BEGIN -----", file=sys.stderr)
        print(response, file=sys.stderr)
        print("----- LLM RESPONSE END -----", file=sys.stderr)

    def _call_llm(self, diff_content: str) -> ReviewResult:
        """Make LLM API call."""
        client = self._get_client()
        model = self.config.get_model()
        base_url = self.config.get_base_url()

        prompt = self._build_prompt(diff_content)
        prompt_tokens = self._estimate_tokens(prompt)

        self._trace_print(f"LLM Query: model={model}, base_url={base_url}")
        self._trace_print(f"LLM Query: estimated_tokens={prompt_tokens}")
        self._trace_llm_request(prompt, model, base_url)

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,  # Low temperature for consistent analysis
            )
        except OpenAIError as e:
            self._trace_print(f"LLM Query failed: {e}")
            raise e

        # Handle non-standard API responses that return string instead of ChatCompletion object
        if isinstance(response, str):
            raw_response = response
        elif hasattr(response, "choices") and response.choices:
            raw_response = response.choices[0].message.content or ""
        else:
            raise ValueError(
                f"Unexpected response type from LLM API: {type(response).__name__}"
            )
        response_tokens = self._estimate_tokens(raw_response)
        self._trace_print(f"LLM Response: received ~{response_tokens} tokens")
        self._trace_llm_response(raw_response)

        return self._parse_llm_response(raw_response)

    def _parse_llm_response(self, response: str) -> ReviewResult:
        """Parse LLM response into structured result."""
        critical_issues = []
        warnings = []
        suggestions = []

        lines = response.strip().split("\n")

        for line in lines:
            line = line.strip()
            if line.startswith("CRITICAL:"):
                issue = line[9:].strip()
                if issue and issue != "NONE":
                    critical_issues.append(issue)
            elif line.startswith("WARNING:"):
                warning = line[8:].strip()
                if warning and warning != "NONE":
                    warnings.append(warning)
            elif line.startswith("SUGGESTION:"):
                suggestion = line[11:].strip()
                if suggestion and suggestion != "NONE":
                    suggestions.append(suggestion)

        return ReviewResult(
            status="success",
            critical_issues=critical_issues,
            warnings=warnings,
            suggestions=suggestions,
            raw_response=response,
        )

    def _is_retryable_error(self, error: OpenAIError) -> bool:
        """Check if error is retryable."""
        if hasattr(error, "status_code"):
            status = error.status_code
            # Don't retry on client errors (4xx) except 429 (rate limit)
            if 400 <= status < 500 and status not in [429, 408, 429]:
                # 408 Request Timeout, 429 Too Many Requests - retryable
                return False
            # Don't retry on authentication errors
            if status in [401, 403]:
                return False
            # Don't retry on model not found
            if status == 404:
                self.logger.warning("Model not found (404). Check model configuration.")
                return False

        # Retry on network errors, timeouts, server errors (5xx)
        return True

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter."""
        base_delay = 2**attempt
        jitter = random.uniform(0, 1)
        return base_delay + jitter

    def _handle_model_unavailable(
        self, diff_content: str, error: Exception
    ) -> ReviewResult:
        """Handle model unavailability gracefully."""
        self.logger.error(f"Model unavailable: {error}")

        result = ReviewResult(
            status="model_unavailable",
            critical_issues=[],
            warnings=[f"🔴 LLM model unavailable: {str(error)}"],
            suggestions=[],
        )

        # Try fallback model if configured
        fallback_model = self.config.get("llm.fallback_model")
        original_model = None

        if fallback_model:
            try:
                self.logger.info(f"Trying fallback model: {fallback_model}")
                self._trace_print(f"Fallback: trying fallback model {fallback_model}")
                original_model = self.config.config["llm"]["model"]
                self.config.config["llm"]["model"] = fallback_model

                fallback_result = self._call_llm(diff_content)
                fallback_result.fallback_used = True
                fallback_result.warnings.append(
                    "⚠️ Used backup model due to primary unavailability"
                )

                # Restore original model
                if original_model:
                    self.config.config["llm"]["model"] = original_model

                return fallback_result
            except Exception as e:
                self.logger.warning(f"Fallback model also failed: {e}")
                # Restore original model
                if original_model:
                    self.config.config["llm"]["model"] = original_model

        # Use static analysis as final fallback
        if self.config.get("fallback.enable_static_analysis", True):
            self.logger.info("Using static analysis as fallback")
            self._trace_print("Fallback: using static analysis")
            try:
                # Direct import for testing
                import sys
                import os

                sys.path.append(os.path.dirname(__file__))
                from static_analyzer import StaticAnalyzer

                analyzer = StaticAnalyzer(self.config)
                static_result = analyzer.analyze_diff(diff_content)

                result.warnings.extend(static_result.warnings)
                result.suggestions.extend(static_result.suggestions)
            except ImportError as e:
                self.logger.error(f"Static analyzer not available: {e}")

        return result

    def test_connection(self) -> bool:
        """Test connection to LLM."""
        try:
            client = self._get_client()
            model = self.config.get_model()
            base_url = self.config.get_base_url()

            self._trace_print(f"Test connection: model={model}, base_url={base_url}")

            # Simple test message
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": "Test connection. Respond with 'OK'."}
                ],
                max_tokens=10,
            )

            # Handle non-standard API responses
            if isinstance(response, str):
                content = response
            elif hasattr(response, "choices") and response.choices:
                content = response.choices[0].message.content or ""
            else:
                content = ""

            success = content and "OK" in content
            self._trace_print(f"Test connection: success={success}")
            return success
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False
