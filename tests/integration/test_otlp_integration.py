# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import os

import pytest

from provide.telemetry import counter, setup_telemetry, shutdown_telemetry, trace
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.setup import _reset_all_for_tests

pytestmark = [pytest.mark.integration, pytest.mark.otel]


def test_otlp_collector_smoke() -> None:
    pytest.importorskip("opentelemetry")
    endpoint = os.getenv("PROVIDE_TEST_OTLP_ENDPOINT")
    traces_endpoint = os.getenv("PROVIDE_TEST_OTLP_TRACES_ENDPOINT") or endpoint
    metrics_endpoint = os.getenv("PROVIDE_TEST_OTLP_METRICS_ENDPOINT") or endpoint
    otlp_headers = os.getenv("PROVIDE_TEST_OTLP_HEADERS")
    if not traces_endpoint or not metrics_endpoint:
        pytest.skip(
            "PROVIDE_TEST_OTLP_ENDPOINT (or PROVIDE_TEST_OTLP_TRACES_ENDPOINT and PROVIDE_TEST_OTLP_METRICS_ENDPOINT) "
            "is not set"
        )

    _reset_all_for_tests()

    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_SERVICE_NAME": "provide-telemetry-integration",
            "PROVIDE_TRACE_ENABLED": "true",
            "PROVIDE_METRICS_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": traces_endpoint,
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": metrics_endpoint,
            **({"OTEL_EXPORTER_OTLP_HEADERS": otlp_headers} if otlp_headers else {}),
        }
    )
    setup_telemetry(cfg)

    @trace("integration.otlp.smoke")
    def _work() -> dict[str, str | None]:
        otel_trace = pytest.importorskip("opentelemetry.trace")
        counter("integration.requests").add(1, {"suite": "integration"})
        context = otel_trace.get_current_span().get_span_context()
        trace_id = f"{context.trace_id:032x}" if context.trace_id else None
        span_id = f"{context.span_id:016x}" if context.span_id else None
        return {"trace_id": trace_id, "span_id": span_id}

    trace_context = _work()
    assert isinstance(trace_context["trace_id"], str) and len(trace_context["trace_id"]) == 32
    assert isinstance(trace_context["span_id"], str) and len(trace_context["span_id"]) == 16

    shutdown_telemetry()
