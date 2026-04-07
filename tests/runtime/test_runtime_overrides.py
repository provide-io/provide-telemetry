# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for RuntimeOverrides type and update_runtime_config changes."""

from __future__ import annotations

import dataclasses
import logging

import pytest

from provide.telemetry import backpressure as backpressure_mod
from provide.telemetry import health as health_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry import runtime as runtime_mod
from provide.telemetry import sampling as sampling_mod
from provide.telemetry.config import (
    BackpressureConfig,
    ExporterPolicyConfig,
    RuntimeOverrides,
    SamplingConfig,
    SecurityConfig,
    SLOConfig,
    TelemetryConfig,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    health_mod.reset_health_for_tests()
    sampling_mod.reset_sampling_for_tests()
    backpressure_mod.reset_queues_for_tests()
    resilience_mod.reset_resilience_for_tests()
    runtime_mod.reset_runtime_for_tests()


def test_runtime_overrides_accepts_hot_fields() -> None:
    """RuntimeOverrides can be constructed with all hot-reloadable fields."""
    overrides = RuntimeOverrides(
        sampling=SamplingConfig(logs_rate=0.5),
        backpressure=BackpressureConfig(logs_maxsize=10),
        exporter=ExporterPolicyConfig(logs_retries=3),
        security=SecurityConfig(max_attr_count=32),
        slo=SLOConfig(enable_red_metrics=True),
        pii_max_depth=4,
        strict_schema=True,
    )
    assert overrides.sampling is not None
    assert overrides.sampling.logs_rate == 0.5
    assert overrides.backpressure is not None
    assert overrides.backpressure.logs_maxsize == 10
    assert overrides.exporter is not None
    assert overrides.exporter.logs_retries == 3
    assert overrides.security is not None
    assert overrides.security.max_attr_count == 32
    assert overrides.slo is not None
    assert overrides.slo.enable_red_metrics is True
    assert overrides.pii_max_depth == 4
    assert overrides.strict_schema is True


def test_runtime_overrides_has_no_cold_fields() -> None:
    """RuntimeOverrides must not contain any cold-key fields (service_name, environment, etc.)."""
    field_names = {f.name for f in dataclasses.fields(RuntimeOverrides)}
    cold_keys = {"service_name", "environment", "version", "tracing", "metrics"}
    overlap = field_names & cold_keys
    assert overlap == set(), f"RuntimeOverrides must not contain cold fields: {overlap}"


def test_runtime_overrides_all_fields_optional() -> None:
    """All RuntimeOverrides fields default to None."""
    overrides = RuntimeOverrides()
    assert overrides.sampling is None
    assert overrides.backpressure is None
    assert overrides.exporter is None
    assert overrides.security is None
    assert overrides.slo is None
    assert overrides.pii_max_depth is None
    assert overrides.strict_schema is None


def test_runtime_overrides_validates_pii_max_depth() -> None:
    """RuntimeOverrides validates pii_max_depth when set."""
    from provide.telemetry.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError, match="pii_max_depth must be >= 0"):
        RuntimeOverrides(pii_max_depth=-1)


def test_update_runtime_config_accepts_overrides() -> None:
    """update_runtime_config accepts RuntimeOverrides and returns TelemetryConfig."""
    overrides = RuntimeOverrides(
        sampling=SamplingConfig(logs_rate=0.3, traces_rate=0.4, metrics_rate=0.5),
    )
    result = runtime_mod.update_runtime_config(overrides)
    assert isinstance(result, TelemetryConfig)
    assert result.sampling.logs_rate == pytest.approx(0.3)
    assert result.sampling.traces_rate == pytest.approx(0.4)
    assert result.sampling.metrics_rate == pytest.approx(0.5)
    # Verify policies were actually applied
    assert sampling_mod.get_sampling_policy("logs").default_rate == pytest.approx(0.3)


def test_update_runtime_config_preserves_unset_fields() -> None:
    """Fields not set in RuntimeOverrides keep their current values."""
    # Set up a base config with distinctive values
    base = TelemetryConfig(
        service_name="my-svc",
        environment="staging",
        sampling=SamplingConfig(logs_rate=0.1),
        backpressure=BackpressureConfig(logs_maxsize=42),
        pii_max_depth=5,
    )
    runtime_mod.apply_runtime_config(base)

    # Override only sampling
    overrides = RuntimeOverrides(
        sampling=SamplingConfig(logs_rate=0.9),
    )
    result = runtime_mod.update_runtime_config(overrides)

    # Sampling was overridden
    assert result.sampling.logs_rate == pytest.approx(0.9)
    # Cold fields preserved
    assert result.service_name == "my-svc"
    assert result.environment == "staging"
    # Other hot fields preserved
    assert result.backpressure.logs_maxsize == 42
    assert result.pii_max_depth == 5


def test_update_runtime_config_overrides_each_field_independently() -> None:
    """Each RuntimeOverrides field is applied independently."""
    base = TelemetryConfig(
        sampling=SamplingConfig(logs_rate=0.1),
        backpressure=BackpressureConfig(logs_maxsize=10),
        security=SecurityConfig(max_attr_count=16),
        slo=SLOConfig(enable_red_metrics=False),
        pii_max_depth=3,
    )
    runtime_mod.apply_runtime_config(base)

    # Override security and pii_max_depth only
    overrides = RuntimeOverrides(
        security=SecurityConfig(max_attr_count=128),
        pii_max_depth=12,
        strict_schema=True,
    )
    result = runtime_mod.update_runtime_config(overrides)

    assert result.security.max_attr_count == 128
    assert result.pii_max_depth == 12
    assert result.strict_schema is True
    # Others unchanged
    assert result.sampling.logs_rate == pytest.approx(0.1)
    assert result.backpressure.logs_maxsize == 10
    assert result.slo.enable_red_metrics is False


def test_reload_runtime_from_env_warns_on_cold_change(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """reload_runtime_from_env logs a warning when cold fields have drifted."""
    # Set up a base with a known service_name
    base = TelemetryConfig(service_name="original-svc", environment="prod")
    runtime_mod.apply_runtime_config(base)

    # Make from_env return different cold fields
    changed = TelemetryConfig(service_name="new-svc", environment="prod")
    monkeypatch.setattr(
        "provide.telemetry.runtime.TelemetryConfig.from_env",
        classmethod(lambda cls: changed),
    )

    with caplog.at_level(logging.WARNING, logger="provide.telemetry.runtime"):
        runtime_mod.reload_runtime_from_env()

    assert any("runtime.cold_field_drift" in record.message for record in caplog.records)
    drift_record = next(r for r in caplog.records if "runtime.cold_field_drift" in r.message)
    assert "service_name" in drift_record.fields  # type: ignore[attr-defined]


def test_reload_runtime_from_env_no_active_config(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """reload_runtime_from_env works when no config has been applied yet (cold-drift check skipped)."""
    env_cfg = TelemetryConfig(sampling=SamplingConfig(logs_rate=0.7))
    monkeypatch.setattr(
        "provide.telemetry.runtime.TelemetryConfig.from_env",
        classmethod(lambda cls: env_cfg),
    )

    with caplog.at_level(logging.WARNING, logger="provide.telemetry.runtime"):
        result = runtime_mod.reload_runtime_from_env()

    assert not any("runtime.cold_field_drift" in record.message for record in caplog.records)
    assert result.sampling.logs_rate == pytest.approx(0.7)


def test_reload_runtime_from_env_no_warning_when_cold_unchanged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """reload_runtime_from_env does not warn when cold fields haven't changed."""
    base = TelemetryConfig(service_name="svc", environment="dev")
    runtime_mod.apply_runtime_config(base)

    # Same cold fields, different hot field
    changed = TelemetryConfig(
        service_name="svc",
        environment="dev",
        sampling=SamplingConfig(logs_rate=0.5),
    )
    monkeypatch.setattr(
        "provide.telemetry.runtime.TelemetryConfig.from_env",
        classmethod(lambda cls: changed),
    )

    with caplog.at_level(logging.WARNING, logger="provide.telemetry.runtime"):
        result = runtime_mod.reload_runtime_from_env()

    assert not any("runtime.cold_field_drift" in record.message for record in caplog.records)
    assert result.sampling.logs_rate == pytest.approx(0.5)
