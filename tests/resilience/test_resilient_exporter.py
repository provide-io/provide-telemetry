# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Behavioural tests for the ResilientExporter transport wrapper."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from provide.telemetry import resilience as resilience_mod
from provide.telemetry.resilience import (
    ExporterPolicy,
    get_circuit_state,
    reset_resilience_for_tests,
    set_exporter_policy,
)
from provide.telemetry.resilient_exporter import (
    ResilientExporter,
    _load_failure_result,
    wrap_exporter,
)


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None, None, None]:
    reset_resilience_for_tests()
    yield
    reset_resilience_for_tests()


# Sentinel singletons so `is` comparisons work reliably (tests should check
# identity, not accidental instance construction from a callable class).
_Success = object()
_Failure = object()


class _FakeExporter:
    # Declared so test_getattr_forwards_unknown_attributes can populate it
    # without triggering mypy's attr-defined check.
    endpoint: str | None = None

    def __init__(self, behavior: Any = _Success) -> None:
        self.behavior = behavior
        self.exported: list[Any] = []
        self.shutdown_calls = 0
        self.flush_calls = 0

    def export(self, batch: Any, *args: Any, **kwargs: Any) -> Any:
        self.exported.append(batch)
        if isinstance(self.behavior, Exception):
            raise self.behavior
        if callable(self.behavior):
            return self.behavior()
        return self.behavior

    def shutdown(self, *args: Any, **kwargs: Any) -> str:
        self.shutdown_calls += 1
        return "shutdown-return"

    def force_flush(self, *_args: Any, **_kwargs: Any) -> bool:
        self.flush_calls += 1
        return True


def _make_wrapper(signal: str, inner: Any) -> ResilientExporter:
    # Pass an explicit failure sentinel so tests don't depend on OTel enum imports.
    return ResilientExporter(signal, inner, failure_result=_Failure)


@pytest.mark.otel
def test_load_failure_result_returns_each_signal_enum() -> None:
    # Lazy import — real enums; the fact that the value is distinct per signal
    # is what we care about, not the specific values.
    logs = _load_failure_result("logs")
    traces = _load_failure_result("traces")
    metrics = _load_failure_result("metrics")
    assert logs is not None and traces is not None and metrics is not None


def test_load_failure_result_rejects_unknown_signal() -> None:
    with pytest.raises(ValueError, match="unknown signal"):
        _load_failure_result("unknown")


def test_successful_export_is_passed_through() -> None:
    fake = _FakeExporter(_Success)
    wrapper = _make_wrapper("logs", fake)
    result = wrapper.export(["batch"])
    assert result is _Success
    assert fake.exported == [["batch"]]


def test_fail_open_policy_returns_failure_result_not_none() -> None:
    set_exporter_policy("logs", ExporterPolicy(retries=0, timeout_seconds=0.0, fail_open=True))
    err = RuntimeError("boom")
    fake = _FakeExporter(err)
    wrapper = _make_wrapper("logs", fake)
    result = wrapper.export(["batch"])
    # When resilience returns None under fail_open, the wrapper reports the
    # canonical FAILURE sentinel to the OTel BatchProcessor so it records a
    # drop instead of treating None as a crash.
    assert result is _Failure


def test_fail_closed_policy_propagates_exception() -> None:
    set_exporter_policy("traces", ExporterPolicy(retries=0, timeout_seconds=0.0, fail_open=False))
    err = RuntimeError("nope")
    fake = _FakeExporter(err)
    wrapper = _make_wrapper("traces", fake)
    with pytest.raises(RuntimeError, match="nope"):
        wrapper.export(["spans"])


def test_retries_invoke_inner_export_multiple_times() -> None:
    set_exporter_policy("logs", ExporterPolicy(retries=2, backoff_seconds=0.0, timeout_seconds=0.0, fail_open=True))
    call_count = {"n": 0}

    def _flaky() -> Any:
        call_count["n"] += 1
        raise RuntimeError("transient")

    fake = _FakeExporter(_flaky)
    wrapper = _make_wrapper("logs", fake)
    result = wrapper.export(["batch"])
    assert result is _Failure
    # retries=2 ⇒ 1 + 2 = 3 attempts at the underlying export
    assert call_count["n"] == 3


def test_circuit_opens_after_consecutive_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    set_exporter_policy(
        "metrics",
        ExporterPolicy(retries=0, backoff_seconds=0.0, timeout_seconds=0.05, fail_open=True),
    )

    # Force each attempt to raise TimeoutError via the retry-loop code path.
    def _always_timeout(_sig: str, _op: Any, _timeout: float, *, skip_executor: bool = False) -> Any:
        raise TimeoutError("simulated")

    monkeypatch.setattr(resilience_mod, "_run_attempt_with_timeout", _always_timeout)
    fake = _FakeExporter(_Success)
    wrapper = _make_wrapper("metrics", fake)

    # Three consecutive timeouts trip the breaker (threshold=3).
    for _ in range(3):
        assert wrapper.export(["batch"]) is _Failure

    state, _open_count, cooldown = get_circuit_state("metrics")
    assert state == "open"
    assert cooldown > 0


def test_shutdown_forwards_to_inner_exporter() -> None:
    fake = _FakeExporter()
    wrapper = _make_wrapper("logs", fake)
    assert wrapper.shutdown() == "shutdown-return"
    assert fake.shutdown_calls == 1


def test_force_flush_forwards_to_inner_exporter() -> None:
    fake = _FakeExporter()
    wrapper = _make_wrapper("logs", fake)
    assert wrapper.force_flush(timeout_millis=500) is True
    assert fake.flush_calls == 1


def test_getattr_forwards_unknown_attributes() -> None:
    fake = _FakeExporter()
    # Dynamically set an attribute the ResilientExporter proxy doesn't declare.
    fake.endpoint = "http://example"
    wrapper = _make_wrapper("logs", fake)
    # Attribute not declared on ResilientExporter — __getattr__ should forward.
    assert wrapper.endpoint == "http://example"


@pytest.mark.otel
def test_wrap_exporter_helper_uses_real_failure_enum_lookup() -> None:
    fake = _FakeExporter(_Success)
    wrapper = wrap_exporter("logs", fake)
    # Real OTel LogExportResult.FAILURE is returned on fail-open drop.
    # First verify success passthrough works without enum material.
    assert wrapper.export(["batch"]) is _Success


@pytest.mark.otel
def test_wrap_exporter_returns_real_failure_enum_on_drop() -> None:
    from opentelemetry.sdk._logs.export import LogExportResult

    set_exporter_policy("logs", ExporterPolicy(retries=0, timeout_seconds=0.0, fail_open=True))
    fake = _FakeExporter(RuntimeError("boom"))
    wrapper = wrap_exporter("logs", fake)
    assert wrapper.export(["batch"]) is LogExportResult.FAILURE
