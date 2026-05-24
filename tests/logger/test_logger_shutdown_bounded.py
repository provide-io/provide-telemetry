# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for shutdown_logging's bounded flush+shutdown wiring."""

from __future__ import annotations

import pytest

from provide.telemetry.logger import core as core_mod


def test_shutdown_logging_passes_configured_timeout_to_bounded_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The active config's logs_shutdown_timeout_seconds must flow into the bounded helper.

    Pins the wiring between LoggingConfig and bounded_provider_shutdown so a
    refactor cannot accidentally drop the per-deployment override on the floor.
    """
    from provide.telemetry import resilience as resilience_mod
    from provide.telemetry.config import ExporterPolicyConfig, TelemetryConfig

    captured: dict[str, object] = {}

    def _spy(provider: object, timeout_seconds: float) -> bool:
        captured["provider"] = provider
        captured["timeout"] = timeout_seconds
        return True

    monkeypatch.setattr(resilience_mod, "bounded_provider_shutdown", _spy)

    sentinel = object()
    core_mod._otel_log_provider = sentinel
    core_mod._active_config = TelemetryConfig(exporter=ExporterPolicyConfig(logs_shutdown_timeout_seconds=2.5))
    core_mod._configured = True

    core_mod.shutdown_logging()
    assert captured["provider"] is sentinel
    assert captured["timeout"] == 2.5
    assert core_mod._otel_log_provider is None
    assert core_mod._active_config is None
    assert core_mod._configured is False


def test_shutdown_logging_uses_default_timeout_when_no_active_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback to 5.0s when shutdown_logging runs without an installed config snapshot.

    Reproduces a path where teardown ordering leaves a provider live but
    _active_config already cleared — the bounded helper must still receive a
    sane (non-None) timeout instead of crashing on attribute access.
    """
    from provide.telemetry import resilience as resilience_mod

    captured: dict[str, float] = {}

    def _spy(_provider: object, timeout_seconds: float) -> bool:
        captured["timeout"] = timeout_seconds
        return True

    monkeypatch.setattr(resilience_mod, "bounded_provider_shutdown", _spy)

    core_mod._otel_log_provider = object()
    core_mod._active_config = None
    core_mod.shutdown_logging()
    assert captured["timeout"] == 5.0
