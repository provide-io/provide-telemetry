# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""OTLP endpoint validation helpers."""

from __future__ import annotations

from urllib.parse import urlparse

_VALID_PORT_RANGE = range(1, 65536)


def validate_otlp_endpoint(endpoint: str | None) -> str:
    """Return endpoint when it is a valid absolute OTLP HTTP URL, else raise ValueError."""
    if endpoint is None:
        raise ValueError("invalid OTLP endpoint: None")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.hostname is None:
        raise ValueError(f"invalid OTLP endpoint: {endpoint!r}")
    # Force port evaluation — urlparse silently accepts non-numeric or
    # out-of-range ports (e.g. "http://host:bad", "http://host:99999").
    # Without this check, setup succeeds but export fails asynchronously.
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid OTLP endpoint port: {endpoint!r}") from exc
    if port is not None and port not in _VALID_PORT_RANGE:
        raise ValueError(f"invalid OTLP endpoint port: {endpoint!r}")
    return endpoint
