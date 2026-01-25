"""
Core LLM integration for code review system.
Based on existing hello_llm.py structure.
"""

import os
import time
import random
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

from openai import OpenAI, OpenAIError


@dataclass
class ReviewResult:
    """Result of LLM code review."""
    status: str  # "success", "model_unavailable", "error"
    critical_issues: List[str]
    warnings: List[str]
    suggestions: List[str]
    fallback_used: bool = False
    raw_response: Optional[str] = None


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

    def __init__(self, config):
        self.config = config
        self.client = None
        self._setup_logging()

    def _build_prompt(self, diff_content: str) -> str:
        """Build review prompt from config or use default."""
        prompt_config = self.config.get("prompt") or {}
        if not isinstance(prompt_config, dict):
            prompt_config = {}

        custom_prompt = prompt_config.get("custom_prompt")
        if custom_prompt and isinstance(custom_prompt, str):
            try:
                return custom_prompt.format(diff_content=diff_content)
            except KeyError as e:
                self.logger.warning(f"Custom prompt has invalid placeholder: {e}. Using default.")

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

        critical_str = "\n".join(f"- {rule}" for rule in custom_critical if isinstance(rule, str))
        warnings_str = "\n".join(f"- {rule}" for rule in custom_warnings if isinstance(rule, str))
        suggestions_str = "\n".join(f"- {rule}" for rule in custom_suggestions if isinstance(rule, str))

        try:
            return self.DEFAULT_PROMPT.format(
                diff_content=diff_content,
                custom_critical_rules=critical_str,
                custom_warnings=warnings_str,
                custom_suggestions=suggestions_str,
                additional_instructions=additional
            )
        except KeyError as e:
            self.logger.error(f"Prompt template error: {e}. Using minimal prompt.")
            return f"Review this code diff for security issues:\n\n{diff_content}"
    
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
                raise ValueError("API key not found. Set LLM_API_KEY environment variable.")
            
            base_url = self.config.get_base_url()
            timeout = self.config.get("llm.timeout", 30)
            
            self.client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=timeout
            )
        
        return self.client
    
    def review_diff(self, diff_content: str) -> ReviewResult:
        """Review code diff using LLM with retry and fallback."""
        if not diff_content.strip() or diff_content == "No code changes to review.":
            return ReviewResult(
                status="success",
                critical_issues=[],
                warnings=[],
                suggestions=[]
            )
        
        max_retries = self.config.get("llm.max_retries", 3)
        
        for attempt in range(max_retries):
            try:
                return self._call_llm(diff_content)
            except OpenAIError as e:
                self.logger.warning(f"LLM call failed (attempt {attempt + 1}/{max_retries}): {e}")
                
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
                    suggestions=[]
                )
        
        # Fallback in case all retries fail
        return ReviewResult(
            status="error",
            critical_issues=["All retry attempts failed"],
            warnings=[],
            suggestions=[]
        )
    
    def _call_llm(self, diff_content: str) -> ReviewResult:
        """Make LLM API call."""
        client = self._get_client()
        model = self.config.get_model()

        prompt = self._build_prompt(diff_content)
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,  # Low temperature for consistent analysis
            )
        except OpenAIError as e:
            raise e
        
        raw_response = response.choices[0].message.content or ""
        return self._parse_llm_response(raw_response)
    
    def _parse_llm_response(self, response: str) -> ReviewResult:
        """Parse LLM response into structured result."""
        critical_issues = []
        warnings = []
        suggestions = []
        
        lines = response.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if line.startswith('CRITICAL:'):
                issue = line[9:].strip()
                if issue and issue != 'NONE':
                    critical_issues.append(issue)
            elif line.startswith('WARNING:'):
                warning = line[8:].strip()
                if warning and warning != 'NONE':
                    warnings.append(warning)
            elif line.startswith('SUGGESTION:'):
                suggestion = line[11:].strip()
                if suggestion and suggestion != 'NONE':
                    suggestions.append(suggestion)
        
        return ReviewResult(
            status="success",
            critical_issues=critical_issues,
            warnings=warnings,
            suggestions=suggestions,
            raw_response=response
        )
    
    def _is_retryable_error(self, error: OpenAIError) -> bool:
        """Check if error is retryable."""
        if hasattr(error, 'status_code'):
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
                self.logger.warning(f"Model not found (404). Check model configuration.")
                return False
        
        # Retry on network errors, timeouts, server errors (5xx)
        return True
    
    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter."""
        base_delay = 2 ** attempt
        jitter = random.uniform(0, 1)
        return base_delay + jitter
    
    def _handle_model_unavailable(self, diff_content: str, error: Exception) -> ReviewResult:
        """Handle model unavailability gracefully."""
        self.logger.error(f"Model unavailable: {error}")
        
        result = ReviewResult(
            status="model_unavailable",
            critical_issues=[],
            warnings=[f"🔴 LLM model unavailable: {str(error)}"],
            suggestions=[]
        )
        
        # Try fallback model if configured
        fallback_model = self.config.get("llm.fallback_model")
        original_model = None
        
        if fallback_model:
            try:
                self.logger.info(f"Trying fallback model: {fallback_model}")
                original_model = self.config.config["llm"]["model"]
                self.config.config["llm"]["model"] = fallback_model
                
                fallback_result = self._call_llm(diff_content)
                fallback_result.fallback_used = True
                fallback_result.warnings.append("⚠️ Used backup model due to primary unavailability")
                
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
            
            # Simple test message
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Test connection. Respond with 'OK'."}],
                max_tokens=10
            )
            
            return response.choices[0].message.content and "OK" in response.choices[0].message.content
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False