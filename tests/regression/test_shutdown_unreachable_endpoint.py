# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression: shutdown_telemetry must not hang when OTLP logs endpoint is unreachable.

Setup with ``OTEL_EXPORTER_OTLP_ENDPOINT`` pointing at a closed local port
historically caused ``shutdown_telemetry()`` to block in
``BatchLogRecordProcessor.force_flush`` for tens of seconds while the OTLP HTTP
exporter retried with exponential backoff. The fix wraps the
``force_flush``+``shutdown`` sequence in a daemon thread bounded by
``PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS``.

This test reproduces the original Octowright report: real OTel SDK installed,
real ``OTEL_EXPORTER_OTLP_ENDPOINT`` set, no collector listening — the entire
setup/log/shutdown round-trip must complete within a few seconds.
"""

from __future__ import annotations

import socket
import time
import warnings
from collections.abc import Generator

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import get_logger
from provide.telemetry.setup import _reset_all_for_tests, setup_telemetry, shutdown_telemetry

pytestmark = pytest.mark.otel


@pytest.fixture
def _unreachable_port() -> Generator[int, None, None]:
    """Reserve a local TCP port, then close the socket so connects refuse instantly."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()  # closing makes connect() return ECONNREFUSED immediately
    yield port


def test_shutdown_returns_quickly_with_unreachable_otlp_endpoint(
    monkeypatch: pytest.MonkeyPatch, _unreachable_port: int
) -> None:
    pytest.importorskip("opentelemetry")
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http")

    # Mimic the Octowright shell: OTEL_EXPORTER_OTLP_ENDPOINT inherited from the
    # environment, pointing at a port where nothing is listening.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{_unreachable_port}")
    # Bound shutdown to 1s. Leave per-export timeout at its 10s default so that
    # WITHOUT the bounded-shutdown fix this test would block for ~10s in
    # BatchLogRecordProcessor.force_flush. The 1s shutdown deadline must
    # take precedence and abandon the pending flush.
    monkeypatch.setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "1.0")
    # Disable trace/metrics setup — only the logs OTLP path is under test, and
    # we want to prove that disabling trace/metrics is NOT sufficient on its own.
    monkeypatch.setenv("PROVIDE_TRACE_ENABLED", "false")
    monkeypatch.setenv("PROVIDE_METRICS_ENABLED", "false")

    _reset_all_for_tests()
    try:
        cfg = TelemetryConfig.from_env()
        setup_telemetry(cfg)
        # Emit a log so there's something in the export queue at shutdown time;
        # otherwise force_flush would return immediately even without the fix.
        get_logger("regression").info("unreachable_endpoint_probe")

        # Record warnings out-of-band so we can assert on BOTH elapsed time
        # and the abandon warning without one masking the other. Pre-fix, the
        # elapsed assertion is the primary failure signal; the warning check
        # then proves the bounded helper actually fired post-fix.
        started = time.monotonic()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            shutdown_telemetry()
        elapsed = time.monotonic() - started
    finally:
        _reset_all_for_tests()

    # 1s shutdown deadline + measurement noise. Pre-fix this regularly took
    # 7-10s because BatchLogRecordProcessor.shutdown joined the worker
    # thread while the OTLP exporter's internal retry chain ran to its own
    # deadline.
    assert elapsed < 3.0, f"shutdown_telemetry took {elapsed:.2f}s, expected <3s"
    abandon_warnings = [
        w
        for w in caught
        if issubclass(w.category, RuntimeWarning) and "exceeded" in str(w.message) and "deadline" in str(w.message)
    ]
    assert abandon_warnings, "expected bounded_provider_shutdown to warn about abandoned flush"


def test_disable_log_otlp_avoids_shutdown_hang_entirely(
    monkeypatch: pytest.MonkeyPatch, _unreachable_port: int
) -> None:
    """PROVIDE_LOG_OTLP_ENABLED=false must skip OTLP wiring so shutdown is instant.

    Documents the supported escape hatch: callers that don't want log OTLP but
    still want trace/metrics OTLP can opt out per-signal. shutdown returns
    well under the bounded-flush deadline because no OTLP handler was attached
    in the first place.
    """
    pytest.importorskip("opentelemetry")

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{_unreachable_port}")
    monkeypatch.setenv("PROVIDE_LOG_OTLP_ENABLED", "false")
    monkeypatch.setenv("PROVIDE_TRACE_ENABLED", "false")
    monkeypatch.setenv("PROVIDE_METRICS_ENABLED", "false")

    _reset_all_for_tests()
    try:
        setup_telemetry(TelemetryConfig.from_env())
        get_logger("regression").info("disabled_log_otlp_probe")
        started = time.monotonic()
        shutdown_telemetry()
        elapsed = time.monotonic() - started
    finally:
        _reset_all_for_tests()

    assert elapsed < 2.0, f"shutdown_telemetry took {elapsed:.2f}s with logs OTLP disabled"
