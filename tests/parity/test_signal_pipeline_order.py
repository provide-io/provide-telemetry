# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Canonical signal pipeline order -- ``spec/pipeline_fixtures.yaml``.

The TypeScript, Rust and C# suites run their real logger against the fixture;
this is Python's. Stages are observed on the shipping structlog pipeline, not a
model of it: each one is detected by wrapping the function the pipeline itself
calls for that stage, and ``local`` / ``backend`` are the fan-out handler's two
children. ``health`` is any emitted or dropped count, wherever the pipeline
takes it -- the sampler and the queue count their own drops.

Every case must match its fixture path exactly, rejections included: a refused
record counts its drop and then runs the release stage, releasing the ticket it
never took (None).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from provide.telemetry import backpressure, consent, health, pii, receipts, sampling
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import core, processors

_FIXTURE = Path(__file__).parent.parent.parent / "spec" / "pipeline_fixtures.yaml"

# Every fixture stage this harness can see on the logs pipeline.
_OBSERVABLE = (
    "consent",
    "sampling",
    "backpressure",
    "hardening",
    "pii",
    "receipt",
    "local",
    "backend",
    "health",
    "release",
)


def _fixture() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    return loaded


def _expected(case_id: str) -> list[str]:
    case = next(case for case in _fixture()["cases"] if case["id"] == case_id)
    return [stage for stage in case["expected"] if stage in _OBSERVABLE]


class _Stage(logging.Handler):
    def __init__(self, stage: str, seen: list[str], *, fail: bool = False) -> None:
        super().__init__()
        self._stage = stage
        self._seen = seen
        self._fail = fail

    def emit(self, record: logging.LogRecord) -> None:
        self._seen.append(self._stage)
        if self._fail:
            # Contained the way a real exporter handler contains it: emit()
            # never raises, it reports through handleError.
            try:
                raise RuntimeError("backend rejected the record")
            except RuntimeError:
                self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        """A failing backend is part of the case, not noise for stderr."""
        self._seen.append("backend:error")


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    observed: list[str] = []

    def _wrap(module: Any, name: str, stage: str) -> None:
        real: Callable[..., Any] = getattr(module, name)

        def _observed(*args: Any, **kwargs: Any) -> Any:
            observed.append(stage)
            return real(*args, **kwargs)

        monkeypatch.setattr(module, name, _observed)

    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    # sanitize_sensitive_fields binds sanitize_payload when the chain is built,
    # so it is wrapped before configuring; the rest are looked up per record.
    _wrap(processors, "_harden_keys", "hardening")
    _wrap(pii, "sanitize_payload", "pii")
    core.configure_logging(TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": "json"}), force=True)
    receipts._reset_receipts_for_tests()
    receipts.enable_receipts(enabled=True, service_name="pipeline-svc")
    real_hook = pii._receipt_hook
    assert real_hook is not None

    def _receipt(field_path: str, action: str, value: Any) -> None:
        observed.append("receipt")
        real_hook(field_path, action, value)

    monkeypatch.setattr(pii, "_receipt_hook", _receipt)
    _wrap(consent, "should_allow", "consent")
    _wrap(sampling, "should_sample", "sampling")
    _wrap(backpressure, "try_acquire", "backpressure")
    _wrap(backpressure, "release", "release")
    _wrap(health, "increment_emitted", "health")
    _wrap(health, "increment_dropped", "health")
    # The sampler and the queue bound increment_dropped at import.
    _wrap(sampling, "increment_dropped", "health")
    _wrap(backpressure, "increment_dropped", "health")
    try:
        yield observed
    finally:
        receipts._reset_receipts_for_tests()
        core._reset_logging_for_tests()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def _run(seen: list[str], *, backend_fails: bool = False, with_backend: bool = True) -> list[str]:
    fanout = core._installed_fanout()
    assert fanout is not None
    children: list[logging.Handler] = [_Stage("local", seen)]
    if with_backend:
        children.append(_Stage("backend", seen, fail=backend_fails))
    fanout.replace_children(children)
    seen.clear()
    core.get_logger("pipeline").info("pipeline.probe.ok", password="pipeline-secret")  # pragma: allowlist secret
    return [stage for stage in seen if stage in _OBSERVABLE]


def _ticket_is_free() -> bool:
    ticket = backpressure.try_acquire("logs")
    if ticket is None:
        return False
    backpressure.release(ticket)
    return True


# ── every path, exactly as the fixture lists it ──────────────────────────────


@pytest.mark.parametrize(
    ("case_id", "backend"),
    [("local_only_success", "none"), ("backend_success", "ok"), ("backend_failure", "fails")],
)
def test_admitted_path_matches_the_fixture_exactly(seen: list[str], case_id: str, backend: str) -> None:
    before = health.get_health_snapshot()
    observed = _run(seen, with_backend=backend != "none", backend_fails=backend == "fails")
    after = health.get_health_snapshot()
    assert observed == _expected(case_id)
    # Emitted once, never dropped, whether or not the backend accepted it.
    assert after.emitted_logs - before.emitted_logs == 1
    assert after.dropped_logs == before.dropped_logs
    assert _ticket_is_free()


def test_consent_rejection_matches_the_fixture_exactly(seen: list[str]) -> None:
    consent.set_consent_level(consent.ConsentLevel.NONE)
    before = health.get_health_snapshot()
    assert _run(seen) == _expected("consent_rejection")
    after = health.get_health_snapshot()
    # A consent refusal is a drop, and only a drop.
    assert after.dropped_logs - before.dropped_logs == 1
    assert after.emitted_logs == before.emitted_logs
    assert _ticket_is_free()


def test_sampling_rejection_matches_the_fixture_exactly(seen: list[str]) -> None:
    sampling.set_sampling_policy("logs", sampling.SamplingPolicy(default_rate=0.0))
    before = health.get_health_snapshot()
    assert _run(seen) == _expected("sampling_rejection")
    after = health.get_health_snapshot()
    assert after.dropped_logs - before.dropped_logs == 1
    assert after.emitted_logs == before.emitted_logs


def test_queue_rejection_matches_the_fixture_and_leaks_no_capacity(seen: list[str]) -> None:
    backpressure.set_queue_policy(backpressure.QueuePolicy(logs_maxsize=1))
    held = backpressure.try_acquire("logs")
    assert held is not None
    before = health.get_health_snapshot()
    assert _run(seen) == _expected("queue_rejection")
    after = health.get_health_snapshot()
    assert after.dropped_logs - before.dropped_logs == 1
    assert after.emitted_logs == before.emitted_logs
    # The held ticket is still the only one out: the queue stays full.
    assert backpressure.try_acquire("logs") is None
    backpressure.release(held)


def test_the_backend_failure_case_really_fails(seen: list[str]) -> None:
    """The failure is reported through handleError, not lost, and not raised."""
    _run(seen, backend_fails=True)
    assert seen.count("backend:error") == 1
    _run(seen)
    assert "backend:error" not in seen
