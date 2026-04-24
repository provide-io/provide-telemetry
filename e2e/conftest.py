# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Shared fixtures for cross-language E2E tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture()
def repo_root() -> Path:
    """Return the repository root path."""
    return REPO_ROOT


@pytest.fixture()
def mock_otlp_receiver() -> Iterator[object]:
    """Stand up an in-process OTLP/HTTP mock receiver for the duration of a test.

    The receiver binds to an ephemeral port on 127.0.0.1 and accepts POSTs on
    ``/v1/traces``, ``/v1/logs``, and ``/v1/metrics``.  Captured spans are
    available via ``.spans_for_trace(trace_id)`` once they have been exported.

    Skips the test if ``opentelemetry-proto`` is not installed (i.e. the
    ``otel`` extra is absent).
    """

    pytest.importorskip("opentelemetry.proto.collector.trace.v1.trace_service_pb2")
    # Imported lazily to keep default test collection free of OTel deps.
    from e2e.backends.mock_otlp_receiver import MockOtlpReceiver

    receiver = MockOtlpReceiver()
    receiver.start()
    try:
        yield receiver
    finally:
        receiver.stop()
