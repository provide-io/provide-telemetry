#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Memray stress test for propagation + baggage parsing."""

from __future__ import annotations

from provide.telemetry.propagation import (
    bind_propagation_context,
    clear_propagation_context,
    extract_w3c_context,
    parse_baggage,
)

BAGGAGE = "userId=alice,tenant=acme,requestId=req-123;ttl=30,env=prod"
SCOPE: dict[str, object] = {
    "type": "http",
    "headers": [
        (b"traceparent", b"00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"),
        (b"tracestate", b"congo=t61rcWkgMzE"),
        (b"baggage", BAGGAGE.encode()),
    ],
}


def main() -> None:
    """Run propagation stress cycles."""
    # parse_baggage: 500K cycles
    for _ in range(500_000):
        parse_baggage(BAGGAGE)

    # Full propagation cycle: 100K cycles
    for _ in range(100_000):
        ctx = extract_w3c_context(SCOPE)
        bind_propagation_context(ctx)
        clear_propagation_context()


if __name__ == "__main__":
    main()
