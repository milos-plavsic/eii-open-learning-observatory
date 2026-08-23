# Contributing

Thank you for helping improve the EII Open Learning Observatory.

## Before opening a change

- Use synthetic, openly licensed, or explicitly authorized course material.
- Never commit learner conversations, personal data, credentials, private
  keys, production databases, or confidential publisher content.
- Open an issue before a compatibility-breaking schema or CLI change.
- Report suspected vulnerabilities privately as described in `SECURITY.md`.

## Development checks

The project supports Python 3.11 through 3.14. Before submitting a pull
request, run:

```bash
uv sync --extra dev
uv run ruff check src tests tools
uv run ruff format --check src tests tools
uv run mypy
uv run python tools/maintainability_gate.py
uv run coverage erase
PYTHONWARNINGS=error uv run coverage run -m unittest discover -s tests -p 'test_*.py'
uv run coverage report
uv run python tests/mutation_probe.py
```

Coverage is branch-aware and must remain at 100% of tracked code; the fixed
declaration-only exclusion count is documented in `docs/testing-policy.md`.
Pull requests should include
tests for new behavior and update relevant schemas and documentation.

## Pull requests

Keep changes focused and explain the educational use case, evidence boundary,
privacy implications, and verification performed. By contributing, you agree
that your contribution is licensed under the repository's MIT License.
