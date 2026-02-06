# CHANGES

## [Unreleased]

### Added
- `--offline` CLI flag: run static analysis only, without any LLM calls. No API key
  or network connection required. Automatically forces `check_docstrings: True`.
  Mutually exclusive with `--test-connection`. Useful for quick local checks,
  CI environments without API access, or when no internet is available.
- Docstrings suggestions feature: detects functions, methods, and classes missing
  documentation comments in added code. Supports Python docstrings, JSDoc (JS/TS/JSX/TSX),
  Javadoc, Doxygen (C/C++), godoc (Go), and Rust doc comments. Works in both static analysis fallback
  and LLM-powered review modes. Controlled by `review.check_docstrings` config option.

### TODO
- VSCode extension integration: provide real-time code review feedback directly
  in the editor via a dedicated VSCode extension.
- PyCharm/IntelliJ IDEA plugin integration: provide code review inspections
  and quick-fixes via a dedicated JetBrains IDE plugin.

