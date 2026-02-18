# Contributing

Contributions are welcome — especially new transform scripts!

## Adding a transform script

1. Create a `.py` file in `transforms/`.
2. Define a `transform(text: str) -> str` function.
3. Add a module-level docstring — it appears as the description in the UI.

```python
"""Convert text to SHOUTING CASE."""

def transform(text: str) -> str:
    return text.upper()
```

That's it. ClipCommand will pick it up on the next **Rescan** without restarting.

## Reporting bugs

Please open a GitHub issue and include:
- Your OS and Python version (`python --version`)
- The full traceback from the log window (copy it out of the UI)
- The transform script that triggered the problem, if applicable

## Pull requests

- Keep PRs focused — one feature or fix per PR.
- Transform scripts should have a clear docstring and handle exceptions gracefully
  (return an error string rather than raising, so the user sees something useful).
- `clipcommand.py` changes should not introduce new required dependencies beyond
  `pyperclip` and stdlib.

## Code style

- Standard library `tkinter` only for the UI — no third-party GUI frameworks.
- PEP 8, 4-space indents, type hints where practical.
- Keep the dark Dracula-ish colour scheme consistent if touching the UI.
