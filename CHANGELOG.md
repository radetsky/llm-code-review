# CHANGES

## [Unreleased]

### Added
- Docstrings suggestions feature: detects functions, methods, and classes missing
  documentation comments in added code. Supports Python docstrings, JSDoc (JS/TS/JSX/TSX),
  Javadoc, Doxygen (C/C++), godoc (Go), and Rust doc comments. Works in both static analysis fallback
  and LLM-powered review modes. Controlled by `review.check_docstrings` config option.

### TODO
- VSCode extension integration: provide real-time code review feedback directly
  in the editor via a dedicated VSCode extension.
- PyCharm/IntelliJ IDEA plugin integration: provide code review inspections
  and quick-fixes via a dedicated JetBrains IDE plugin.

