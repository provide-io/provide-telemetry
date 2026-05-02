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
    assert "service_name" in drift_record.fields  # type: ignore


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


def test_overrides_from_config_extracts_all_hot_fields() -> None:
    """Kill mutants that set fields to None or remove them in _overrides_from_config.

    Every hot-reloadable field must be faithfully extracted from the full
    TelemetryConfig into RuntimeOverrides with distinct non-default values.
    """
    cfg = TelemetryConfig(
        sampling=SamplingConfig(logs_rate=0.11, traces_rate=0.22, metrics_rate=0.33),
        backpressure=BackpressureConfig(logs_maxsize=7, traces_maxsize=8, metrics_maxsize=9),
        exporter=ExporterPolicyConfig(logs_retries=4),
        security=SecurityConfig(max_attr_count=77),
        slo=SLOConfig(enable_red_metrics=True, enable_use_metrics=True),
        pii_max_depth=13,
        strict_schema=True,
    )
    overrides = runtime_mod._overrides_from_config(cfg)

    # Each field must match the source config (not None, not default)
    assert overrides.sampling is cfg.sampling
    assert overrides.backpressure is cfg.backpressure
    assert overrides.exporter is cfg.exporter
    assert overrides.security is cfg.security
    assert overrides.slo is cfg.slo
    assert overrides.pii_max_depth == 13
    assert overrides.strict_schema is True


def test_overrides_from_config_backpressure_not_none() -> None:
    """Kill mutmut_2/9: backpressure=None or omitted."""
    cfg = TelemetryConfig(
        backpressure=BackpressureConfig(logs_maxsize=42),
    )
    overrides = runtime_mod._overrides_from_config(cfg)
    assert overrides.backpressure is not None
    assert overrides.backpressure.logs_maxsize == 42


def test_overrides_from_config_security_not_none() -> None:
    """Kill mutmut_4/11: security=None or omitted."""
    cfg = TelemetryConfig(
        security=SecurityConfig(max_attr_count=99),
    )
    overrides = runtime_mod._overrides_from_config(cfg)
    assert overrides.security is not None
    assert overrides.security.max_attr_count == 99


def test_overrides_from_config_slo_not_none() -> None:
    """Kill mutmut_5/12: slo=None or omitted."""
    cfg = TelemetryConfig(
        slo=SLOConfig(enable_red_metrics=True),
    )
    overrides = runtime_mod._overrides_from_config(cfg)
    assert overrides.slo is not None
    assert overrides.slo.enable_red_metrics is True


def test_overrides_from_config_pii_max_depth_not_none() -> None:
    """Kill mutmut_6/13: pii_max_depth=None or omitted."""
    cfg = TelemetryConfig(pii_max_depth=17)
    overrides = runtime_mod._overrides_from_config(cfg)
    assert overrides.pii_max_depth == 17


def test_overrides_from_config_strict_schema_not_none() -> None:
    """Kill mutmut_7/14: strict_schema=None or omitted."""
    cfg = TelemetryConfig(strict_schema=True)
    overrides = runtime_mod._overrides_from_config(cfg)
    assert overrides.strict_schema is True


def test_apply_overrides_deepcopy_isolates_base() -> None:
    """Kill mutmut_3: copy.deepcopy -> copy.copy.

    With a shallow copy, mutating a nested config object on the merged result
    would also mutate the base. A deepcopy prevents this.
    """
    base = TelemetryConfig(
        sampling=SamplingConfig(logs_rate=0.1),
    )
    overrides = RuntimeOverrides()  # no overrides
    merged = runtime_mod._apply_overrides(base, overrides)

    # Mutate the merged result's nested sampling config
    merged.sampling.logs_rate = 0.99

    # Base must be unaffected (deepcopy isolates)
    assert base.sampling.logs_rate == pytest.approx(0.1)


def test_apply_overrides_slo_applied() -> None:
    """Kill mutmut_13: merged.slo = overrides.slo -> merged.slo = None."""
    base = TelemetryConfig(
        slo=SLOConfig(enable_red_metrics=False),
    )
    new_slo = SLOConfig(enable_red_metrics=True, enable_use_metrics=True)
    overrides = RuntimeOverrides(slo=new_slo)
    merged = runtime_mod._apply_overrides(base, overrides)
    assert merged.slo is not None
    assert merged.slo.enable_red_metrics is True
    assert merged.slo.enable_use_metrics is True


def test_reload_runtime_from_env_warning_extra_keys(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Kill mutmut_18/22/23/24/25: exact message string and extra dict content."""
    base = TelemetryConfig(service_name="old-svc", environment="prod")
    runtime_mod.apply_runtime_config(base)

    changed = TelemetryConfig(service_name="new-svc", environment="prod")
    monkeypatch.setattr(
        "provide.telemetry.runtime.TelemetryConfig.from_env",
        classmethod(lambda cls: changed),
    )

    with caplog.at_level(logging.WARNING, logger="provide.telemetry.runtime"):
        runtime_mod.reload_runtime_from_env()

    drift_records = [r for r in caplog.records if "cold_field_drift" in r.message]
    assert len(drift_records) >= 1
    rec = drift_records[0]
    # Kill mutmut_18: exact message string
    assert rec.message == "runtime.cold_field_drift"
    # Kill mutmut_22/23: "action" key must exist (not "XXactionXX" or "ACTION")
    assert hasattr(rec, "action"), "extra dict must contain 'action' key"
    # Kill mutmut_24/25: exact value
    assert rec.action == "restart required to apply"


def test_concurrent_reconfigure_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent calls to reconfigure_telemetry() must not raise."""
    import threading

    runtime_mod.reset_runtime_for_tests()
    monkeypatch.setattr(
        "provide.telemetry.runtime.TelemetryConfig.from_env",
        classmethod(lambda cls: TelemetryConfig()),
    )
    import importlib

    logger_core = importlib.import_module("provide.telemetry.logger.core")
    monkeypatch.setattr(logger_core, "_has_otel_log_provider", lambda: False)
    monkeypatch.setattr(
        "provide.telemetry.tracing.provider._has_tracing_provider",
        lambda: False,
    )
    monkeypatch.setattr(
        "provide.telemetry.metrics.provider._has_meter_provider",
        lambda: False,
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.shutdown_telemetry",
        lambda: None,
    )
    monkeypatch.setattr(
        "provide.telemetry.setup.setup_telemetry",
        lambda cfg: cfg,
    )

    errors: list[Exception] = []

    def _reconfigure() -> None:
        try:
            runtime_mod.reconfigure_telemetry()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_reconfigure) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert errors == []


def test_reconfigure_lock_exists() -> None:
    """_reconfigure_lock must exist and be a threading.Lock-compatible object."""
    import threading

    lock = runtime_mod._reconfigure_lock
    assert hasattr(lock, "acquire")
    assert hasattr(lock, "release")
    assert isinstance(lock, type(threading.Lock()))


def test_get_strict_schema_returns_false_by_default() -> None:
    """get_strict_schema() returns False when config has strict_schema=False."""
    runtime_mod.apply_runtime_config(TelemetryConfig(strict_schema=False))
    assert runtime_mod.get_strict_schema() is False


def test_set_strict_schema_enables_flag() -> None:
    """set_strict_schema(True) updates strict_schema in the active runtime config."""
    runtime_mod.apply_runtime_config(TelemetryConfig(strict_schema=False))
    runtime_mod.set_strict_schema(True)
    assert runtime_mod.get_strict_schema() is True


def test_set_strict_schema_disables_flag() -> None:
    """set_strict_schema(False) clears strict_schema in the active runtime config."""
    runtime_mod.apply_runtime_config(TelemetryConfig(strict_schema=True))
    runtime_mod.set_strict_schema(False)
    assert runtime_mod.get_strict_schema() is False


def test_get_strict_schema_reads_from_env_when_no_config() -> None:
    """get_strict_schema() falls back to env-derived config when no active config is set."""
    runtime_mod.reset_runtime_for_tests()
    # With no active config, get_runtime_config() returns TelemetryConfig.from_env().
    # The default is False.
    result = runtime_mod.get_strict_schema()
    assert isinstance(result, bool)


def test_update_runtime_config_rebuilds_logging_on_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """When logging config changes via RuntimeOverrides, the structlog
    pipeline is rebuilt via configure_logging(force=True)."""
    from provide.telemetry.config import LoggingConfig, RuntimeOverrides

    monkeypatch.delenv("PROVIDE_LOG_LEVEL", raising=False)
    runtime_mod.reset_runtime_for_tests()
    runtime_mod.apply_runtime_config(TelemetryConfig.from_env())
    before = runtime_mod.get_runtime_config()
    assert before.logging.level == "INFO"

    new_logging = LoggingConfig(
        level="DEBUG",
        fmt=before.logging.fmt,
        include_timestamp=before.logging.include_timestamp,
    )
    updated = runtime_mod.update_runtime_config(RuntimeOverrides(logging=new_logging))
    assert updated.logging.level == "DEBUG"
