# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Drift guard: every env var in config.py must appear in docs/CONFIGURATION.md."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PY = _ROOT / "src" / "undef" / "telemetry" / "config.py"
_CONFIG_MD = _ROOT / "docs" / "CONFIGURATION.md"

# Matches data.get("UNDEF_*") and data.get("OTEL_EXPORTER_OTLP_*") calls in from_env().
_ENV_VAR_RE = re.compile(r'data\.get\(\s*"((?:UNDEF_|OTEL_EXPORTER_OTLP_)[A-Z_]+)"')


def _extract_env_vars_from_config() -> set[str]:
    source = _CONFIG_PY.read_text(encoding="utf-8")
    # Only parse the from_env() method body.
    start = source.find("def from_env(")
    assert start != -1, "could not find from_env() in config.py"
    body = source[start:]
    return set(_ENV_VAR_RE.findall(body))


def _extract_documented_vars() -> set[str]:
    content = _CONFIG_MD.read_text(encoding="utf-8")
    # Match backtick-wrapped env var names in markdown table cells.
    return set(re.findall(r"`((?:UNDEF_|OTEL_EXPORTER_OTLP_)[A-Z_]+)`", content))


@pytest.mark.tooling
def test_all_env_vars_documented() -> None:
    """Every env var parsed in config.py:from_env() must appear in CONFIGURATION.md."""
    code_vars = _extract_env_vars_from_config()
    doc_vars = _extract_documented_vars()
    assert code_vars, "failed to extract any env vars from config.py"
    assert doc_vars, "failed to extract any env vars from CONFIGURATION.md"
    missing = code_vars - doc_vars
    assert not missing, f"env vars in config.py but not in CONFIGURATION.md: {sorted(missing)}"


@pytest.mark.tooling
def test_no_stale_documented_vars() -> None:
    """Every UNDEF_*/OTEL_EXPORTER_OTLP_* var in CONFIGURATION.md should exist in config.py."""
    code_vars = _extract_env_vars_from_config()
    doc_vars = _extract_documented_vars()
    # Exclude OpenObserve vars (not in config.py) and OTEL_EXPORTER_OTLP_HEADERS (shared fallback).
    external_vars = {
        "OPENOBSERVE_URL",
        "OPENOBSERVE_USER",
        "OPENOBSERVE_PASSWORD",
        "OPENOBSERVE_REQUIRED_SIGNALS",
    }
    stale = (doc_vars - code_vars) - external_vars
    assert not stale, f"env vars in CONFIGURATION.md but not in config.py: {sorted(stale)}"
