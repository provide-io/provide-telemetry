# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Canonical signal pipeline order -- ``spec/pipeline_fixtures.yaml``.

The TypeScript, Rust and C# suites run their real logger against the fixture;
this is Python's. Stages are observed on the shipping structlog pipeline, not a
model of it: each one is detected by wrapping the function the pipeline itself
calls for that stage, and ``local`` / ``backend`` are the fan-out handler's two
children.

Python does **not** match the fixture on two points, and the strict xfails
below record exactly where, so a fix flips them to XPASS and fails the run:

* ``hardening`` runs *before* admission. ``harden_input`` sits ahead of
  ``apply_sampling`` in the processor chain, so a record consent or sampling
  is about to drop is hardened first.
* ``health`` is counted *at* admission. ``apply_sampling`` increments
  ``emitted_logs`` as soon as a ticket is taken, ahead of PII, receipts and
  both handlers, where the fixture places it after the backend.

A rejected record never takes a ticket, so it has none to release -- the
fixture's ``release`` on rejection paths is not observable here (Rust's suite
says the same and checks capacity instead, as this one does).
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
    return list(seen)


def _ticket_is_free() -> bool:
    ticket = backpressure.try_acquire("logs")
    if ticket is None:
        return False
    backpressure.release(ticket)
    return True


# ── what Python already shares with the fixture ──────────────────────────────


@pytest.mark.parametrize(
    ("case_id", "backend"),
    [("local_only_success", "none"), ("backend_success", "ok"), ("backend_failure", "fails")],
)
def test_admitted_records_run_the_payload_stages_in_canonical_order(
    seen: list[str], case_id: str, backend: str
) -> None:
    observed = _run(seen, with_backend=backend != "none", backend_fails=backend == "fails")
    tail = ["pii", "receipt", "local", "backend", "release"]
    expected = [stage for stage in _expected(case_id) if stage in tail]
    assert [stage for stage in observed if stage in tail] == expected
    assert ("backend:error" in observed) is (backend == "fails")
    assert observed.count("release") == 1
    assert _ticket_is_free()


def test_admission_runs_consent_then_sampling_then_backpressure(seen: list[str]) -> None:
    observed = _run(seen)
    admission = [stage for stage in observed if stage in ("consent", "sampling", "backpressure")]
    assert admission == ["consent", "sampling", "backpressure"]


def test_consent_rejection_does_no_payload_work(seen: list[str]) -> None:
    consent.set_consent_level(consent.ConsentLevel.NONE)
    observed = _run(seen)
    assert "consent" in observed
    assert not {"sampling", "backpressure", "pii", "receipt", "local", "backend"} & set(observed)
    assert _ticket_is_free()


def test_sampling_rejection_stops_before_backpressure(seen: list[str]) -> None:
    sampling.set_sampling_policy("logs", sampling.SamplingPolicy(default_rate=0.0))
    observed = _run(seen)
    assert observed[-2:] == ["consent", "sampling"]
    assert not {"backpressure", "pii", "receipt", "local", "backend"} & set(observed)


def test_queue_rejection_leaks_no_capacity(seen: list[str]) -> None:
    backpressure.set_queue_policy(backpressure.QueuePolicy(logs_maxsize=1))
    held = backpressure.try_acquire("logs")
    assert held is not None
    observed = _run(seen)
    assert observed[-3:] == ["consent", "sampling", "backpressure"]
    assert not {"pii", "receipt", "local", "backend", "release"} & set(observed)
    # The held ticket is still the only one out: the queue stays full.
    assert backpressure.try_acquire("logs") is None
    backpressure.release(held)


# ── where Python diverges: recorded, not papered over ─────────────────────────

_DIVERGES = pytest.mark.xfail(
    strict=True,
    reason="Python hardens before admission and counts health at admission; see module docstring",
)


@_DIVERGES
@pytest.mark.parametrize(
    ("case_id", "backend"),
    [("local_only_success", "none"), ("backend_success", "ok"), ("backend_failure", "fails")],
)
def test_admitted_path_matches_the_fixture_exactly(seen: list[str], case_id: str, backend: str) -> None:
    observed = _run(seen, with_backend=backend != "none", backend_fails=backend == "fails")
    assert [stage for stage in observed if stage in _OBSERVABLE] == _expected(case_id)


@_DIVERGES
def test_consent_rejection_matches_the_fixture_exactly(seen: list[str]) -> None:
    consent.set_consent_level(consent.ConsentLevel.NONE)
    assert _run(seen) == _expected("consent_rejection")


def test_the_divergence_is_the_one_documented(seen: list[str]) -> None:
    """Pins today's order, so the xfails above cannot pass or fail for another reason."""
    assert _run(seen) == [
        "hardening",
        "consent",
        "sampling",
        "backpressure",
        "health",
        "pii",
        "receipt",
        "local",
        "backend",
        "release",
    ]
