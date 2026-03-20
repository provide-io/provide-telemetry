#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Memray stress test for PII sanitization engine."""

from __future__ import annotations

from undef.telemetry.pii import PIIRule, register_pii_rule, replace_pii_rules, sanitize_payload

FLAT_PAYLOAD = {
    "user_id": "u-1234",
    "password": "secret123",
    "token": "tok_abc",
    "api_key": "key_xyz",
    "request_id": "req-001",
}

NESTED_PAYLOAD = {
    "user": {
        "name": "alice",
        "password": "hidden",
        "profile": {"secret": "deep", "email": "a@b.com"},
    },
    "headers": {"authorization": "Bearer tok123"},
    "data": [{"token": "t1"}, {"token": "t2"}, {"api_key": "k1"}],
}

CUSTOM_RULES = [
    PIIRule(path=("user", "name"), mode="truncate", truncate_to=4),
    PIIRule(path=("user", "profile", "email"), mode="hash"),
    PIIRule(path=("headers", "authorization"), mode="redact"),
    PIIRule(path=("data", "*", "token"), mode="drop"),
]


def main() -> None:
    """Run PII sanitization stress cycles."""
    # Flat payloads with default rules only: 200K cycles
    replace_pii_rules([])
    for _ in range(200_000):
        sanitize_payload(FLAT_PAYLOAD, enabled=True)

    # Nested payloads with default rules: 100K cycles
    for _ in range(100_000):
        sanitize_payload(NESTED_PAYLOAD, enabled=True)

    # Nested payloads with custom rules (triggers deep copy): 100K cycles
    replace_pii_rules([])
    for rule in CUSTOM_RULES:
        register_pii_rule(rule)
    for _ in range(100_000):
        sanitize_payload(NESTED_PAYLOAD, enabled=True)

    # Disabled path (should be near-zero allocation): 100K cycles
    for _ in range(100_000):
        sanitize_payload(FLAT_PAYLOAD, enabled=False)

    # Cleanup
    replace_pii_rules([])


if __name__ == "__main__":
    main()
