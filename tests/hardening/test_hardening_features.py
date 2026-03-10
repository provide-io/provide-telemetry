# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

from typing import Any

import pytest

from undef.telemetry import backpressure as backpressure_mod
from undef.telemetry import cardinality as cardinality_mod
from undef.telemetry import health as health_mod
from undef.telemetry import pii as pii_mod
from undef.telemetry import propagation as propagation_mod
from undef.telemetry import resilience as resilience_mod
from undef.telemetry import runtime as runtime_mod
from undef.telemetry import sampling as sampling_mod
from undef.telemetry import slo as slo_mod
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger.context import clear_context, get_context
from undef.telemetry.slo import classify_error, record_red_metrics, record_use_metrics
from undef.telemetry.tracing.context import get_trace_context, set_trace_context


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    health_mod.reset_health_for_tests()
    sampling_mod.reset_sampling_for_tests()
    backpressure_mod.reset_queues_for_tests()
    resilience_mod.reset_resilience_for_tests()
    cardinality_mod.clear_cardinality_limits()
    pii_mod.reset_pii_rules_for_tests()
    clear_context()
    set_trace_context(None, None)


def test_propagation_extract_bind_and_clear() -> None:
    scope = {
        "headers": [
            (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
            (b"tracestate", b"vendor=value"),
            (b"baggage", b"k=v"),
        ]
    }
    ctx = propagation_mod.extract_w3c_context(scope)
    assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert ctx.span_id == "00f067aa0ba902b7"
    propagation_mod.bind_propagation_context(ctx)
    traceparent = get_context()["traceparent"]
    assert isinstance(traceparent, str)
    assert traceparent.startswith("00-")
    assert get_trace_context()["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    propagation_mod.clear_propagation_context()
    assert get_trace_context() == {"trace_id": None, "span_id": None}


def test_propagation_invalid_traceparent_branches() -> None:
    bad_scope = {"headers": [(b"traceparent", b"bad"), (b"tracestate", b"ts")]}
    ctx = propagation_mod.extract_w3c_context(bad_scope)
    assert ctx.trace_id is None
    assert ctx.span_id is None
    wrong_lengths = propagation_mod.extract_w3c_context({"headers": [(b"traceparent", b"00-123-456-01")]})
    assert wrong_lengths.trace_id is None


def test_sampling_policies_and_drop_accounting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("random.random", lambda: 0.0)
    sampling_mod.set_sampling_policy("logs", sampling_mod.SamplingPolicy(default_rate=0.4, overrides={"evt": 0.9}))
    assert sampling_mod.should_sample("logs", "evt") is True
    assert sampling_mod.get_sampling_policy("logs").default_rate == 0.4
    monkeypatch.setattr("random.random", lambda: 1.0)
    sampling_mod.set_sampling_policy("logs", sampling_mod.SamplingPolicy(default_rate=0.0, overrides={"evt": 1.0}))
    assert sampling_mod.should_sample("logs", "other") is False
    snapshot = health_mod.get_health_snapshot()
    assert snapshot.dropped_logs == 1


def test_backpressure_queue_limits_and_release_paths() -> None:
    backpressure_mod.set_queue_policy(backpressure_mod.QueuePolicy(logs_maxsize=1, traces_maxsize=0, metrics_maxsize=0))
    first = backpressure_mod.try_acquire("logs")
    second = backpressure_mod.try_acquire("logs")
    assert first is not None
    assert second is None
    backpressure_mod.release(first)
    backpressure_mod.release(first)
    tokenless = backpressure_mod.try_acquire("traces")
    assert tokenless is not None
    backpressure_mod.release(tokenless)
    unknown = backpressure_mod.try_acquire("unknown")
    assert unknown is not None
    backpressure_mod.release(None)
    backpressure_mod.release(backpressure_mod.QueueTicket(signal="unknown", token=9999))


def test_resilience_success_fail_open_and_fail_closed() -> None:
    resilience_mod.set_exporter_policy(
        "metrics", resilience_mod.ExporterPolicy(retries=1, backoff_seconds=0.01, fail_open=True)
    )
    calls = {"count": 0}

    def _flaky() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return "ok"

    assert resilience_mod.run_with_resilience("metrics", _flaky) == "ok"
    assert health_mod.get_health_snapshot().retries_metrics == 1

    resilience_mod.set_exporter_policy("traces", resilience_mod.ExporterPolicy(retries=0, fail_open=True))
    assert resilience_mod.run_with_resilience("traces", lambda: (_ for _ in ()).throw(ValueError("x"))) is None

    resilience_mod.set_exporter_policy("logs", resilience_mod.ExporterPolicy(retries=0, fail_open=False))
    with pytest.raises(ValueError, match="hard"):
        resilience_mod.run_with_resilience("logs", lambda: (_ for _ in ()).throw(ValueError("hard")))


def test_cardinality_guard_with_ttl_and_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    now = {"value": 1000.0}
    monkeypatch.setattr("time.monotonic", lambda: now["value"])
    cardinality_mod.register_cardinality_limit("user_id", max_values=1, ttl_seconds=10)
    out_a = cardinality_mod.guard_attributes({"user_id": "a"})
    out_a_repeat = cardinality_mod.guard_attributes({"user_id": "a"})
    out_b = cardinality_mod.guard_attributes({"user_id": "b"})
    assert out_a["user_id"] == "a"
    assert out_a_repeat["user_id"] == "a"
    assert out_b["user_id"] == cardinality_mod.OVERFLOW_VALUE

    now["value"] = 1200.0
    out_c = cardinality_mod.guard_attributes({"user_id": "c"})
    assert out_c["user_id"] == "c"
    assert "user_id" in cardinality_mod.get_cardinality_limits()
    cardinality_mod._prune_expired("missing", 1.0)
    cardinality_mod.clear_cardinality_limits()
    assert cardinality_mod.get_cardinality_limits() == {}


def test_pii_engine_default_and_rules() -> None:
    payload: dict[str, Any] = {
        "password": "p",
        "nested": {"token": "t", "secret": "s"},
        "items": [{"key": "v1"}, {"key": "v2"}],
    }
    cleaned = pii_mod.sanitize_payload(payload, enabled=True)
    assert cleaned["password"] == "***"
    assert cleaned["nested"]["token"] == "***"

    pii_mod.replace_pii_rules(
        [
            pii_mod.PIIRule(path=("nested", "secret"), mode="drop"),
            pii_mod.PIIRule(path=("items", "*", "key"), mode="truncate", truncate_to=1),
            pii_mod.PIIRule(path=("password",), mode="hash"),
            pii_mod.PIIRule(path=("nested", "token"), mode="redact"),
        ]
    )
    ruled = pii_mod.sanitize_payload(payload, enabled=True)
    assert "secret" not in ruled["nested"]
    assert ruled["items"][0]["key"] == "v..."
    assert len(ruled["password"]) == 12
    pii_mod.register_pii_rule(pii_mod.PIIRule(path=("nested", "token"), mode="redact"))
    assert pii_mod.get_pii_rules()
    assert pii_mod.sanitize_payload(payload, enabled=False) is payload


def test_pii_sanitize_payload_non_dict_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pii_mod, "_apply_default_sensitive_key_redaction", lambda _node: [])
    assert pii_mod.sanitize_payload({"x": "y"}, enabled=True) == {}


def test_runtime_apply_update_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = TelemetryConfig.from_env(
        {
            "UNDEF_SAMPLING_LOGS_RATE": "0.3",
            "UNDEF_BACKPRESSURE_LOGS_MAXSIZE": "5",
            "UNDEF_EXPORTER_LOGS_RETRIES": "2",
        }
    )
    runtime_mod.apply_runtime_config(cfg)
    runtime_cfg = runtime_mod.get_runtime_config()
    assert runtime_cfg.sampling.logs_rate == 0.3
    runtime_cfg.sampling.logs_rate = 1.0
    assert runtime_mod.get_runtime_config().sampling.logs_rate == 0.3
    assert sampling_mod.get_sampling_policy("logs").default_rate == 0.3
    assert backpressure_mod.get_queue_policy().logs_maxsize == 5
    assert resilience_mod.get_exporter_policy("logs").retries == 2
    cfg.sampling.logs_rate = 0.9
    assert runtime_mod.get_runtime_config().sampling.logs_rate == 0.3
    assert sampling_mod.get_sampling_policy("logs").default_rate == 0.3
    updated = runtime_mod.update_runtime_config(cfg)
    assert updated is not cfg
    assert updated.sampling.logs_rate == 0.9
    assert runtime_mod.get_runtime_config().sampling.logs_rate == 0.9

    monkeypatch.setattr("undef.telemetry.runtime.TelemetryConfig.from_env", classmethod(lambda cls: cfg))
    reloaded = runtime_mod.reload_runtime_from_env()
    assert reloaded is not cfg
    assert reloaded.sampling.logs_rate == cfg.sampling.logs_rate


def test_propagation_extra_header_parsing_branches() -> None:
    ctx = propagation_mod.extract_w3c_context({"headers": [(b"traceparent", "bad-format")]})
    assert ctx.traceparent == "bad-format"
    ctx2 = propagation_mod.extract_w3c_context({"headers": [(b"traceparent", 123)]})
    assert ctx2.traceparent is None
    invalid_hex = propagation_mod.extract_w3c_context(
        {"headers": [(b"traceparent", b"00-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-gggggggggggggggg-01")]}
    )
    assert invalid_hex.trace_id is None


def test_health_snapshot_and_unknown_signal_branch() -> None:
    health_mod.set_queue_depth("unknown", 2)
    health_mod.increment_dropped("unknown", 2)
    health_mod.increment_retries("unknown", 1)
    health_mod.record_export_failure("unknown", RuntimeError("nope"))
    health_mod.record_export_success("unknown", 3.4)
    health_mod.increment_exemplar_unsupported(2)
    snap = health_mod.get_health_snapshot()
    assert snap.queue_depth_logs == 2
    assert snap.dropped_logs >= 2
    assert snap.retries_logs >= 1
    assert snap.exemplar_unsupported_total == 2
    assert snap.export_latency_ms_logs == 3.4


def test_slo_helpers_and_error_taxonomy() -> None:
    errors_before = slo_mod._http_errors_total.value
    record_red_metrics("/health", "GET", 200, 12.0)
    record_red_metrics("/health", "GET", 500, 13.0)
    record_red_metrics("/ws", "WS", 1008, 5.0)
    record_use_metrics("cpu", 42)
    assert classify_error("ValueError") == {"error_type": "internal", "error_code": "0", "error_name": "ValueError"}
    assert classify_error("BadRequest", 400)["error_type"] == "client"
    assert classify_error("ServerError", 500)["error_type"] == "server"
    assert slo_mod._http_errors_total.value - errors_before == 1


@pytest.mark.asyncio
async def test_resilience_async_guard_forces_fail_fast_without_override() -> None:
    resilience_mod.set_exporter_policy(
        "logs",
        resilience_mod.ExporterPolicy(
            retries=2, backoff_seconds=0.5, fail_open=True, allow_blocking_in_event_loop=False
        ),
    )
    calls = {"count": 0}

    def _always_fail() -> str:
        calls["count"] += 1
        raise RuntimeError("boom")

    with pytest.warns(RuntimeWarning, match="forcing fail-fast behavior"):
        assert resilience_mod.run_with_resilience("logs", _always_fail) is None
    assert calls["count"] == 1
    assert health_mod.get_health_snapshot().async_blocking_risk_logs == 1


@pytest.mark.asyncio
async def test_resilience_async_guard_allows_blocking_when_explicit() -> None:
    resilience_mod.set_exporter_policy(
        "metrics",
        resilience_mod.ExporterPolicy(
            retries=1, backoff_seconds=0.0, fail_open=True, allow_blocking_in_event_loop=True
        ),
    )
    calls = {"count": 0}

    def _flaky() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return "ok"

    with pytest.warns(RuntimeWarning, match="allows blocking behavior"):
        assert resilience_mod.run_with_resilience("metrics", _flaky) == "ok"
    assert calls["count"] == 2
    snap = health_mod.get_health_snapshot()
    assert snap.async_blocking_risk_metrics == 1
    assert snap.retries_metrics == 1


@pytest.mark.asyncio
async def test_resilience_async_guard_warns_only_once_per_signal() -> None:
    resilience_mod.set_exporter_policy(
        "traces",
        resilience_mod.ExporterPolicy(
            retries=1, backoff_seconds=0.0, fail_open=True, allow_blocking_in_event_loop=True
        ),
    )

    calls = {"count": 0}

    def _always_fail() -> str:
        calls["count"] += 1
        raise RuntimeError("boom")

    with pytest.warns(RuntimeWarning, match="allows blocking behavior"):
        assert resilience_mod.run_with_resilience("traces", _always_fail) is None
    # Warning is suppressed for same signal after first emission.
    assert resilience_mod.run_with_resilience("traces", _always_fail) is None
    assert calls["count"] == 4
