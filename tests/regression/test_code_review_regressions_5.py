# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Regression tests for mutation survivors found in the 2026-03-25 mutation gate run.

All tests in this file use monkeypatching so they work regardless of whether
the optional opentelemetry extras are installed — and therefore run inside the
mutation gate's test selection (which excludes the otel/integration markers).
"""

from __future__ import annotations

import pytest

from undef.telemetry import _otel as otel_mod


# ── _otel.load_otel_trace_api: exact import name ──────────────────────────────
# Mutants: change "opentelemetry.trace" → None / garbled / uppercase.
# The otel-marked tests for this function require OTel to be installed;
# these tests work without it by capturing the name passed to _import_module.


def test_load_otel_trace_api_passes_exact_module_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that replace 'opentelemetry.trace' with None, garbled, or uppercase."""
    captured: list[str | None] = []

    def _fake_import(name: str | None) -> object:
        captured.append(name)
        return object()

    monkeypatch.setattr(otel_mod, "_import_module", _fake_import)
    result = otel_mod.load_otel_trace_api()
    assert captured == ["opentelemetry.trace"]
    assert result is not None


# ── _otel.load_otel_metrics_api: exact import name ────────────────────────────


def test_load_otel_metrics_api_passes_exact_module_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills mutants that replace 'opentelemetry.metrics' with garbled or uppercase."""
    captured: list[str | None] = []

    def _fake_import(name: str | None) -> object:
        captured.append(name)
        return object()

    monkeypatch.setattr(otel_mod, "_import_module", _fake_import)
    result = otel_mod.load_otel_metrics_api()
    assert captured == ["opentelemetry.metrics"]
    assert result is not None


# ── tracing/provider._load_otel_trace_api: _HAS_OTEL guard ────────────────────
# Mutant: flips `if not _HAS_OTEL` → `if _HAS_OTEL`, making the function
# return None when OTel IS present instead of delegating to _otel.


def test_load_otel_trace_api_delegates_when_has_otel_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills the mutant that returns None when _HAS_OTEL is True."""
    from undef.telemetry.tracing import provider as pmod

    sentinel = object()
    monkeypatch.setattr(pmod, "_HAS_OTEL", True)
    monkeypatch.setattr(pmod._otel, "load_otel_trace_api", lambda: sentinel)
    assert pmod._load_otel_trace_api() is sentinel


# ── metrics/provider._load_otel_metrics_api: _HAS_OTEL_METRICS guard ──────────


def test_load_otel_metrics_api_delegates_when_has_otel_metrics_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills the mutant that returns None when _HAS_OTEL_METRICS is True."""
    from undef.telemetry.metrics import provider as mmod

    sentinel = object()
    monkeypatch.setattr(mmod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(mmod._otel, "load_otel_metrics_api", lambda: sentinel)
    assert mmod._load_otel_metrics_api() is sentinel
