"""
Configuration management for LLM code review system.
"""

import os
import json
from typing import Dict, Any, Optional
from pathlib import Path


class ReviewConfig:
    """Manages configuration for LLM code review."""
    
    DEFAULT_CONFIG = {
        "llm": {
            "model": "gpt-oss:20b",
            "base_url": "https://llm.dev.cossacklabs.com/api",
            "api_key_env": "LLM_API_KEY",
            "timeout": 30,
            "max_retries": 3
        },
        "review": {
            "critical_rules": [
                "hardcoded_credentials",
                "sql_injection", 
                "xss_vulnerabilities",
                "unsafe_functions",
                "file_operations_without_validation"
            ],
            "warning_rules": [
                "code_style_violations",
                "potential_bugs",
                "performance_issues",
                "missing_error_handling",
                "documentation_gaps"
            ],
            "file_extensions": [".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".h"],
            "exclude_patterns": [
                "node_modules/",
                ".git/",
                "__pycache__/",
                "*.min.js",
                "*.test.js",
                "*.spec.js"
            ]
        },
        "output": {
            "format": "text",
            "show_context": True,
            "max_context_lines": 3
        },
        "fallback": {
            "enable_static_analysis": True,
            "allow_commit_on_unavailable": True
        }
    }
    
    def __init__(self, config_file: Optional[str] = None):
        self.config_file = config_file or "review_config.json"
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file or use defaults."""
        config_path = Path(self.config_file)
        
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    user_config = json.load(f)
                return self._merge_configs(self.DEFAULT_CONFIG, user_config)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load config file {self.config_file}: {e}")
                print("Using default configuration.")
        
        return self.DEFAULT_CONFIG.copy()
    
    def _merge_configs(self, default: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge user config with defaults."""
        result = default.copy()
        
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def get(self, path: str, default: Any = None) -> Any:
        """Get configuration value by dot-separated path."""
        keys = path.split('.')
        value = self.config
        
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_api_key(self) -> Optional[str]:
        """Get API key from environment. LLM_API_KEY takes precedence."""
        env_key = os.getenv("LLM_API_KEY")
        if env_key:
            return env_key
        api_key_env = self.get("llm.api_key_env")
        return os.getenv(api_key_env)

    def get_base_url(self) -> str:
        """Get LLM base URL. Environment variable takes precedence over config."""
        env_url = os.getenv("LLM_BASE_URL")
        if env_url:
            return env_url
        return self.get("llm.base_url")

    def get_model(self) -> str:
        """Get LLM model name. Environment variable takes precedence over config."""
        env_model = os.getenv("LLM_MODEL")
        if env_model:
            return env_model
        return self.get("llm.model")
    
    def is_file_supported(self, file_path: str) -> bool:
        """Check if file extension is supported for review."""
        path = Path(file_path)
        
        # Check extension
        if path.suffix not in self.get("review.file_extensions", []):
            return False
        
        # Check exclude patterns
        exclude_patterns = self.get("review.exclude_patterns", [])
        for pattern in exclude_patterns:
            if pattern in str(path) or path.match(pattern):
                return False
        
        return True
    
    def save_config(self):
        """Save current configuration to file."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except IOError as e:
            print(f"Error: Could not save config file {self.config_file}: {e}")