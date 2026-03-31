#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Memray stress test for the logging processor chain hot path."""

from __future__ import annotations

from provide.telemetry.logger.context import bind_context, get_context
from provide.telemetry.logger.processors import sanitize_sensitive_fields
from provide.telemetry.pii import sanitize_payload
from provide.telemetry.schema.events import event_name
from provide.telemetry.tracing.context import get_span_id, get_trace_id

# Representative payloads
FLAT_PAYLOAD = {
    "event": "auth.login.success",
    "user_id": "u-1234",
    "password": "secret123",
    "token": "tok_abc",
    "request_id": "req-001",
}

NESTED_PAYLOAD = {
    "event": "api.request.complete",
    "user": {"name": "alice", "password": "hidden", "email": "a@b.com"},
    "headers": {"authorization": "Bearer tok123", "content_type": "application/json"},
    "meta": {"trace_id": "abc", "span_id": "def"},
}

# Segment variants for event_name
SEGMENTS = [
    ("auth", "login", "success"),
    ("api", "request", "complete"),
    ("ws", "message", "received", "ack"),
    ("db", "query", "execute"),
    ("cache", "lookup", "miss", "fallback", "done"),
]


def main() -> None:
    """Run processor chain stress cycles."""
    sanitize = sanitize_sensitive_fields(enabled=True)

    # event_name: 500K cycles
    for _ in range(500_000):
        for segs in SEGMENTS:
            event_name(*segs)

    # sanitize_payload (flat): 200K cycles
    for _ in range(200_000):
        sanitize_payload(FLAT_PAYLOAD, enabled=True)

    # sanitize_payload (nested): 100K cycles
    for _ in range(100_000):
        sanitize_payload(NESTED_PAYLOAD, enabled=True)

    # sanitize processor wrapper: 100K cycles
    for _ in range(100_000):
        sanitize(None, "info", dict(FLAT_PAYLOAD))

    # merge_runtime_context components: 200K cycles
    bind_context(session_id="sess-001", user_id="u-1234")
    for _ in range(200_000):
        get_context()
        get_trace_id()
        get_span_id()


if __name__ == "__main__":
    main()
