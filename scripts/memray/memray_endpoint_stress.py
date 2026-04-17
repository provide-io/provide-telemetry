#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Memray stress test for endpoint validation."""

from __future__ import annotations

from provide.telemetry._endpoint import validate_otlp_endpoint

ENDPOINTS = [
    "http://localhost:4318",
    "https://collector.example.com:4317/v1/traces",
    "http://[::1]:4318",
    "http://host/v1/metrics",
]


def main() -> None:
    """Run endpoint validation stress cycles."""
    for _ in range(500_000):
        for ep in ENDPOINTS:
            validate_otlp_endpoint(ep)


if __name__ == "__main__":
    main()
