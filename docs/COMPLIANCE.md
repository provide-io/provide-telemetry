# Compliance Notes

## Required Gates

- `uvx reuse lint`
- `codespell`
- `ruff format --check`
- `ruff check`
- `mypy`
- `ty`
- `bandit -r src -ll`
- `pytest` with `--cov-fail-under=100`

## SPDX Policy

Python source and test files include Apache-2.0 SPDX headers.

## Security Baseline

- Static analysis via Bandit at medium/high confidence levels (`-ll`).
- Sensitive fields redaction in logger processors for common key names.
