# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests pinning the diagnostic event names _otel emits when OTel is unavailable.

These strings are the identifiers an operator greps for when telemetry silently
degrades to no-op — "why are there no spans?" is answered by finding
``otel.trace.sdk_unavailable`` in debug logs. A mutated or case-folded name makes
that search return nothing, so the names are part of the contract, not decoration.

Each case forces the ImportError branch by making _import_module raise, then
asserts the exact event name on the emitted DEBUG record.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from provide.telemetry import _otel as otel_mod

_CASES = [
    ("otel.import.not_installed", lambda: otel_mod.has_otel(), False),
    ("otel.trace.import_unavailable", lambda: otel_mod.load_otel_trace_api(), None),
    ("otel.trace.sdk_unavailable", lambda: otel_mod.load_otel_tracing_components(), None),
    ("otel.trace.sampler_unavailable", lambda: otel_mod.build_otel_trace_sampler(0.5), None),
    ("otel.metrics.import_unavailable", lambda: otel_mod.load_otel_metrics_api(), None),
    ("otel.metrics.sdk_unavailable", lambda: otel_mod.load_otel_metrics_components(), None),
    ("otel.logs.sdk_unavailable", lambda: otel_mod.load_otel_logs_components(), None),
    ("otel.propagation.attach_skipped", lambda: otel_mod.attach_w3c_context("tp", None), None),
    ("otel.propagation.inject_skipped", lambda: otel_mod.inject_w3c_context({}), False),
    ("otel.propagation.detach_skipped", lambda: otel_mod.detach_w3c_context(object()), None),
    (
        "otel.instrumentation.handler_unavailable",
        lambda: otel_mod.load_instrumentation_logging_handler(),
        None,
    ),
]


@pytest.mark.parametrize(
    ("event_name", "call", "expected"),
    _CASES,
    ids=[c[0] for c in _CASES],
)
def test_unavailable_otel_logs_its_documented_event_name(
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
    event_name: str,
    call: Any,
    expected: object,
) -> None:
    def _always_missing(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(otel_mod, "_import_module", _always_missing)

    with caplog.at_level(logging.DEBUG, logger=otel_mod.__name__):
        result = call()
        assert result is expected

    messages = [r.getMessage() for r in caplog.records if r.name == otel_mod.__name__]
    assert messages == [event_name], f"expected exactly the {event_name!r} degradation event"


def test_detach_with_no_token_is_a_silent_no_op(monkeypatch: Any, caplog: pytest.LogCaptureFixture) -> None:
    """A None token short-circuits before the import, so nothing is logged."""

    def _always_missing(name: str) -> Any:  # pragma: no cover - must never run
        raise AssertionError("import must not be attempted for a None token")

    monkeypatch.setattr(otel_mod, "_import_module", _always_missing)

    with caplog.at_level(logging.DEBUG, logger=otel_mod.__name__):
        otel_mod.detach_w3c_context(None)

    assert [r.getMessage() for r in caplog.records if r.name == otel_mod.__name__] == []
