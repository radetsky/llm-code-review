# LLM Code Review System

Automated code review system using LLM with multiple integration approaches for corporate environments.

## 🚀 Features

- **Multiple Integration Modes**: Terminal CLI, Git Hooks, GitHub Actions
- **Security-First**: Focus on critical vulnerabilities and safety issues
- **Graceful Degradation**: Fallback to static analysis when LLM unavailable
- **Configurable**: Flexible rules and model settings
- **Corporate-Friendly**: Zero external data retention, local processing

## 📋 Installation

### 1. Dependencies
```bash
# Install Python dependencies
pip install -r requirements.txt

# Or using virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### 2. Configuration
```bash
# Copy and edit configuration
cp review_config.json.example review_config.json

# Set your API key
export OPENAI_API_KEY="your-api-key-here"
export LLM_BASE_URL="https://your-llm-endpoint.com/api"
```

### 3. Git Hooks Installation
```bash
# Install automatic git hooks
python install_hooks.py
```

## 🔧 Usage

### Terminal Command
```bash
# Review staged changes (before commit)
python review.py --mode staged

# Review unstaged changes
python review.py --mode unstaged

# Review all changes from HEAD
python review.py --mode all

# Review between branches/commits
python review.py --base main --head feature-branch

# JSON output for CI/CD
python review.py --mode staged --format json

# Strict mode (block on warnings too)
python review.py --mode staged --strict

# Verbose output
python review.py --mode staged --verbose

# Test connection to LLM
python review.py --test-connection
```

### Git Hooks (Automatic)
```bash
# Pre-commit hook runs automatically before commit
git commit -m "Add new feature"

# Pre-push hook runs automatically before push
git push origin main
```

### GitHub Actions (CI/CD)
- Automatic review on Pull Requests
- Results as PR comments
- Status checks: `LLM Review: Passed/Warning/Failed`
- Artifacts with detailed JSON results

## ⚙️ Configuration

### Review Configuration (review_config.json)
```json
{
  "llm": {
    "model": "gpt-4",
    "base_url": "https://api.openai.com/v1",
    "api_key_env": "OPENAI_API_KEY",
    "timeout": 30,
    "max_retries": 3,
    "fallback_model": "gpt-3.5-turbo"
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
    "show_context": true,
    "max_context_lines": 3
  },
  "fallback": {
    "enable_static_analysis": true,
    "allow_commit_on_unavailable": true
  }
}
```

### Environment Variables
```bash
# Required: API key for LLM
OPENAI_API_KEY="your-api-key"

# Optional: Custom API endpoint
LLM_BASE_URL="https://your-llm-endpoint.com/api"

# Optional: Custom configuration file
REVIEW_CONFIG_FILE="custom-config.json"
```

## 🚨 Exit Codes

| Exit Code | Meaning | Git Action |
|-----------|---------|-------------|
| 0 | Success | ✅ Allow |
| 1 | Critical Issues | ❌ Block |
| 2 | Warnings Only | ⚠️ Allow |
| 3 | Model Unavailable | ⚠️ Allow |
| 4 | Configuration Error | ❌ Block |

## 📊 Monitoring

### Health Check
```bash
# Comprehensive system health check
python monitor.py health
```

### Generate Reports
```bash
# Last 7 days report
python monitor.py report --days 7

# Custom period
python monitor.py report --days 30
```

## 🔄 Integration Examples

### Corporate LLM Setup
```json
{
  "llm": {
    "model": "gpt-oss:20b",
    "base_url": "https://llm.corp.company.com/api",
    "api_key_env": "CORP_LLM_API_KEY"
  }
}
```

### Local Model Setup
```json
{
  "llm": {
    "model": "llama-3.1-8b",
    "base_url": "http://localhost:11434/v1",
    "api_key_env": "OLLAMA_API_KEY"
  }
}
```

## 🛡️ Security Features

### Critical Issues (Block Commit)
- Hardcoded credentials, API keys, secrets
- SQL injection, XSS vulnerabilities
- Unsafe functions (eval(), exec(), system())
- Direct file system operations without validation
- Network requests to external endpoints without validation

### Warnings (Allow Commit)
- Code style violations
- Potential bugs and edge cases
- Performance issues
- Missing error handling
- Input validation gaps

### Static Analysis Fallback
- Pattern-based security checks
- No external dependencies
- Works completely offline
- Rules-based vulnerability detection

## 🚀 GitHub Actions Setup

### Repository Secrets
Set these in GitHub repository settings:
- `LLM_API_KEY`: Your LLM API key
- `LLM_BASE_URL`: Your LLM endpoint (optional)

### Workflow Features
- **Pull Request Reviews**: Automatic analysis and commenting
- **Status Checks**: Integration with GitHub branch protection
- **Artifacts**: Detailed JSON results saved as artifacts
- **Fallback Handling**: Graceful degradation when LLM unavailable

## 📁 Project Structure

```
cl-llm/
├── review.py                 # CLI interface
├── review_core.py            # LLM integration
├── diff_parser.py           # Git diff processing
├── config.py                # Configuration management
├── static_analyzer.py       # Fallback static analysis
├── monitor.py               # Monitoring utilities
├── install_hooks.py         # Hook installation
├── hooks/                   # Git hooks scripts
│   ├── pre-commit
│   └── pre-push
├── .github/workflows/       # GitHub Actions
│   └── llm-review.yml
├── review_config.json       # Configuration
├── requirements.txt         # Dependencies
├── logs/                   # Review logs
└── README.md              # This file
```

## 🔧 Troubleshooting

### Common Issues

#### "Model not found" Error
```bash
# Check your configuration
python review.py --test-connection

# Verify model name in review_config.json
# Check API endpoint accessibility
```

#### Git Hooks Not Working
```bash
# Reinstall hooks
python install_hooks.py

# Check hook permissions
ls -la .git/hooks/

# Test manually
.git/hooks/pre-commit
```

#### LLM Unavailable
```bash
# System falls back to static analysis automatically
# Check network connectivity
python monitor.py health
```

### Debug Mode
```bash
# Enable verbose logging
export REVIEW_DEBUG=1
python review.py --mode staged --verbose
```

## 🤝 Contributing

### Adding New Rules
1. Update `static_analyzer.py` with new pattern checks
2. Add rule to `review_config.json`
3. Update documentation
4. Add tests

### Adding New Model Support
1. Update `config.py` with model configuration
2. Add any required API adapters
3. Update documentation
4. Test with `--test-connection`

## 📄 License

Internal corporate use only.

---

## 🆘 Support

For issues and questions:
1. Check troubleshooting section
2. Run `python monitor.py health`
3. Review logs in `logs/` directory
4. Contact infrastructure team for LLM endpoint issues