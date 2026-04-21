#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""🔒 PII masking and cardinality guardrails.

Demonstrates:
- register_pii_rule / replace_pii_rules / get_pii_rules
- All four PII modes: hash, truncate, drop, redact
- Wildcard path matching for list items
- register_cardinality_limit with TTL and OVERFLOW_VALUE
- get_cardinality_limits / clear_cardinality_limits
- Default sensitive-key redaction vs. custom rule precedence
"""

from __future__ import annotations

import os

from provide.telemetry import (
    PIIRule,
    counter,
    event,
    get_logger,
    register_cardinality_limit,
    register_pii_rule,
    setup_telemetry,
    shutdown_telemetry,
)
from provide.telemetry.cardinality import (
    OVERFLOW_VALUE,
    clear_cardinality_limits,
    get_cardinality_limits,
    guard_attributes,
)
from provide.telemetry.pii import get_pii_rules, replace_pii_rules, sanitize_payload


def main() -> None:
    print("🔒 PII & Cardinality Policy Demo\n")

    setup_telemetry()
    log = get_logger("examples.policy")
    token_value = os.getenv("PROVIDE_EXAMPLE_TOKEN", "example-token-from-env")

    # ── 🛡️ Register PII rules ────────────────────────────
    print("🛡️  Registering PII rules...")
    register_pii_rule(PIIRule(path=("user", "email"), mode="hash"))
    register_pii_rule(PIIRule(path=("user", "full_name"), mode="truncate", truncate_to=3))
    register_pii_rule(PIIRule(path=("credit_card",), mode="drop"))
    print(f"  📋 Active rules: {len(get_pii_rules())}")

    # ── 📝 Log with PII fields ───────────────────────────
    log.info(
        event("example", "policy", "pii"),
        user={"email": "dev@example.com", "full_name": "Casey Developer"},
        credit_card="4111111111111111",
        token=token_value,
    )

    # ── 🔀 Wildcard path matching for lists ───────────────
    print("\n🔀 Wildcard path matching on list items...")
    payload = {
        "players": [
            {"secret": "key-aaa", "name": "Alice"},
            {"secret": "key-bbb", "name": "Bob"},
        ]
    }
    replace_pii_rules([PIIRule(path=("players", "*", "secret"), mode="redact")])
    cleaned = sanitize_payload(payload, enabled=True)
    for p in cleaned["players"]:
        print(f"  🎭 {p['name']}: secret={p['secret']}")
    print(f"  📋 Rules after replace: {len(get_pii_rules())}")

    # ── 🎯 Custom rule precedence over default redaction ──
    print("\n🎯 Custom rule vs. default 'password' redaction...")
    replace_pii_rules([PIIRule(path=("password",), mode="truncate", truncate_to=4)])
    result = sanitize_payload({"password": "hunter2"}, enabled=True)
    print(f"  🔑 password → {result['password']}  (custom truncate, not '***')")

    result_short = sanitize_payload({"password": "ab"}, enabled=True)
    print(f"  🔑 short password → {result_short['password']}  (no-op truncate preserved)")

    # ── 🚧 Cardinality limits with overflow ──────────────
    print("\n🚧 Cardinality guard (max_values=2)...")
    replace_pii_rules([])
    register_cardinality_limit("user_id", max_values=2, ttl_seconds=60)

    metric = counter("example.policy.requests")
    for user_id in ("u1", "u2", "u3", "u4"):
        attrs = guard_attributes({"user_id": user_id})
        metric.add(1, attrs)
        is_overflow = attrs["user_id"] == OVERFLOW_VALUE
        icon = "⚠️" if is_overflow else "✅"
        print(f"  {icon} user_id={user_id} → guarded={attrs['user_id']}")

    limits = get_cardinality_limits()
    print(f"\n  📊 Active cardinality limits: {list(limits.keys())}")

    # ── 🧹 Clear cardinality state ───────────────────────
    clear_cardinality_limits()
    print(f"  🧹 After clear: {get_cardinality_limits()}")

    print("\n🏁 Done!")
    shutdown_telemetry()


if __name__ == "__main__":
    main()
