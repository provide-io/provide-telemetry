# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Drift guard: every parsed env var must appear in docs/guide/configuration.md."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_SOURCES = (
    _ROOT / "src" / "provide" / "telemetry" / "config.py",
    _ROOT / "src" / "provide" / "telemetry" / "_config_validation.py",
    _ROOT / "src" / "provide" / "telemetry" / "_config_prometheus.py",
    # consent.py parses PROVIDE_CONSENT_LEVEL directly rather than through
    # TelemetryConfig.from_env(), so it is a config source for drift purposes
    # even though it contributes no field to the dataclass.
    _ROOT / "src" / "provide" / "telemetry" / "consent.py",
)
_CONFIG_MD = _ROOT / "docs" / "guide" / "configuration.md"
_SPEC = _ROOT / "spec" / "telemetry-api.yaml"

# Matches env var string literals used in from_env(), including helper-call
# arguments such as _resolve_otlp_endpoint(..., "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", ...).
_ENV_VAR_RE = re.compile(r'"((?:PROVIDE_|OTEL_EXPORTER_OTLP_)[A-Z_]+)"')


class _RecordingEnv(Mapping[str, str]):
    """An empty environment that remembers every variable name looked up in it."""

    def __init__(self) -> None:
        self.read: set[str] = set()

    def __getitem__(self, key: str) -> str:
        self.read.add(key)
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


def _otlp_tls_env_vars() -> set[str]:
    """The OTLP TLS variables, which _otlp_tls builds from signal and kind.

    No literal name appears in the source for _ENV_VAR_RE to find, so ask the
    resolver itself: with nothing set it reads every per-signal name and then
    every shared one.
    """
    from provide.telemetry._otlp_tls import unreadable

    env = _RecordingEnv()
    for signal in ("logs", "traces", "metrics"):
        unreadable(signal, env)
    return env.read


def _extract_env_vars_from_config() -> set[str]:
    literal = {var for path in _CONFIG_SOURCES for var in _ENV_VAR_RE.findall(path.read_text(encoding="utf-8"))}
    return literal | _otlp_tls_env_vars()


def _non_python_spec_vars() -> set[str]:
    """Config the spec says other SDKs parse but Python does not (yet).

    configuration.md documents every SDK's config, so a variable only Go reads,
    for example, is documented without appearing in the Python sources.
    """
    spec = yaml.safe_load(_SPEC.read_text(encoding="utf-8"))
    return {
        entry["env"]
        for entries in spec["config_defaults"].values()
        for entry in entries
        if "python" not in (entry.get("applicability") or [])
    }


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
    stale = (doc_vars - code_vars) - external_vars - _non_python_spec_vars()
    assert not stale, f"env vars in CONFIGURATION.md but not in config sources: {sorted(stale)}"
