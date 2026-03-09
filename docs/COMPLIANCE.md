# Compliance Notes

## Required Gates

- `uvx reuse lint`
- `codespell`
- `check_spdx_headers.py`
- `ruff format --check`
- `ruff check`
- `mypy`
- `ty`
- `bandit -r src -ll`
- `pytest` with `--cov-fail-under=100`

## SPDX Policy

Python files must start with:

1. optional shebang
2. `SPDX-FileCopyrightText`
3. `SPDX-License-Identifier`
4. `SPDX-Comment`
5. `#` separator line
6. blank line

Use `uv run python scripts/normalize_spdx_headers.py` to auto-fix and
`uv run python scripts/check_spdx_headers.py` to validate.

## Security Baseline

- Static analysis via Bandit at medium/high confidence levels (`-ll`).
- Sensitive fields redaction in logger processors for common key names.
