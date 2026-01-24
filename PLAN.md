# LLM Code Review Implementation Plan

## 🎯 Goal
Automated code review system using corporate LLM (gpt-oss:20b) with three integration approaches:
1. Terminal command for uncommitted changes review
2. Git hooks integration (pre-commit, pre-push)  
3. GitHub Actions workflow with PR comments

## 📋 Communication Rules
- **Communication**: Ukrainian language
- **Code & Comments**: English only
- **Comments**: Only for very complex logic

## 🏗️ Implementation Phases

### Phase 1: Core Infrastructure
1. Create `review_core.py` - LLM integration (based on existing `hello_llm.py`)
2. Create `diff_parser.py` - Git diff processing and structuring
3. Create `config.py` - Configuration management
4. Create `requirements.txt` - Dependencies specification

### Phase 2: Terminal Interface
5. Create `review.py` - CLI interface with argparse
6. Implement retry/fallback mechanism for model unavailability
7. Test with vulnerable code examples

### Phase 3: Git Hooks Integration  
8. Create `hooks/` directory and hook scripts
9. Create `install_hooks.py` - Automatic hook installation
10. Test hooks on real commits

### Phase 4: GitHub Actions
11. Create `.github/workflows/llm-review.yml`
12. Implement PR comments integration
13. Test in CI environment

### Phase 5: Error Handling & Monitoring
14. Add comprehensive error handling (404, 500, rate limits)
15. Implement logging and metrics
16. Documentation and usage instructions

## 🔧 Architecture

### Project Structure
```
cl-llm/
├── review.py                 # CLI interface
├── review_core.py            # LLM integration  
├── diff_parser.py           # Git diff processing
├── config.py                # Configuration management
├── static_analyzer.py       # Fallback static analysis
├── hooks/                   # Git hooks scripts
│   ├── pre-commit
│   └── pre-push
├── .github/workflows/       # GitHub Actions
│   └── llm-review.yml
├── install_hooks.py         # Hook installation script
├── review_config.json       # Configuration file
├── requirements.txt         # Dependencies
└── PLAN.md                 # This file
```

### Exit Codes
- `0` - Success
- `1` - Critical issues (block commit)
- `2` - Warnings only (allow commit)
- `3` - Model unavailable (allow commit with warning)
- `4` - Configuration error (block commit)

### Error Handling Strategy
- **Model unavailable (404/500)**: Warning, allow commit
- **Rate limits**: Retry with exponential backoff
- **Network issues**: Fallback to static analysis
- **Configuration errors**: Block commit with instructions

## 🚀 Usage Examples

### Terminal Commands
```bash
python review.py --mode staged --format text     # Review staged changes
python review.py --mode unstaged --strict        # Review unstaged, block on issues
python review.py --mode all --format json        # Review everything, JSON output
```

### Git Integration
```bash
# Automatic via hooks
git commit -m "feat: add feature"  # Runs pre-commit hook

# Manual installation
python install_hooks.py
```

### CI/CD Integration
- Automatic review on Pull Request
- Results as PR comments
- Status checks: "LLM Review: Passed/Warning/Failed"

## ✅ Success Criteria
1. Terminal command successfully reviews uncommitted changes
2. Git hooks work without blocking development flow
3. GitHub Actions provide useful PR feedback
4. Graceful degradation when LLM is unavailable
5. All code comments in English, communication in Ukrainian