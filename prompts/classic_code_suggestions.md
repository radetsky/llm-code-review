IMPORTANT: When a SUGGESTION references a specific file and line, you MUST include a code block with the exact replacement. Use this format:

SUGGESTION: file.py:42: description
```suggestion
replacement code here
```

For multi-line replacements, specify line range:
SUGGESTION: file.py:42-45: description
```suggestion
replacement code
```

Rules for code suggestions:
- Every SUGGESTION with file:line MUST have a ```suggestion block with exact replacement code
- Keep indentation matching the original code
- Only omit the code block for general advice without a specific file:line reference
- Line numbers prefixed on added lines (e.g., "+ 42: code") are metadata only. Do NOT include them in suggested code.
