# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Drift guard: every parsed env var must appear in docs/CONFIGURATION.md."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_SOURCES = (
    _ROOT / "src" / "provide" / "telemetry" / "config.py",
    _ROOT / "src" / "provide" / "telemetry" / "_config_validation.py",
)
_CONFIG_MD = _ROOT / "docs" / "CONFIGURATION.md"

# Matches env var string literals used in from_env(), including helper-call
# arguments such as _resolve_otlp_endpoint(..., "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", ...).
_ENV_VAR_RE = re.compile(r'"((?:PROVIDE_|OTEL_EXPORTER_OTLP_)[A-Z_]+)"')


def _extract_env_vars_from_config() -> set[str]:
    return {var for path in _CONFIG_SOURCES for var in _ENV_VAR_RE.findall(path.read_text(encoding="utf-8"))}


def _extract_documented_vars() -> set[str]:
    content = _CONFIG_MD.read_text(encoding="utf-8")
    # Match backtick-wrapped env var names in markdown table cells.
    return set(re.findall(r"`((?:PROVIDE_|OTEL_EXPORTER_OTLP_)[A-Z_]+)`", content))


@pytest.mark.tooling
def test_all_env_vars_documented() -> None:
    """Every parsed env var must appear in CONFIGURATION.md."""
    code_vars = _extract_env_vars_from_config()
    doc_vars = _extract_documented_vars()
    assert code_vars, "failed to extract any env vars from config sources"
    assert doc_vars, "failed to extract any env vars from CONFIGURATION.md"
    missing = code_vars - doc_vars
    assert not missing, f"env vars in config sources but not in CONFIGURATION.md: {sorted(missing)}"


@pytest.mark.tooling
def test_no_stale_documented_vars() -> None:
    """Every documented PROVIDE_*/OTEL_EXPORTER_OTLP_* var should exist in config sources."""
    code_vars = _extract_env_vars_from_config()
    doc_vars = _extract_documented_vars()
    # Exclude OpenObserve vars, which belong to verification tooling rather than library config.
    external_vars = {
        "OPENOBSERVE_URL",
        "OPENOBSERVE_USER",
        "OPENOBSERVE_PASSWORD",
        "OPENOBSERVE_REQUIRED_SIGNALS",
    }
    stale = (doc_vars - code_vars) - external_vars
    assert not stale, f"env vars in CONFIGURATION.md but not in config sources: {sorted(stale)}"
