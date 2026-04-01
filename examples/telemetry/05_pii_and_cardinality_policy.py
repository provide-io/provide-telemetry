#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import os

from provide.telemetry import (
    PIIRule,
    counter,
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
    setup_telemetry()
    log = get_logger("examples.policy")
    token_value = os.getenv("PROVIDE_EXAMPLE_TOKEN", "example-token-from-env")

    register_pii_rule(PIIRule(path=("user", "email"), mode="hash"))
    register_pii_rule(PIIRule(path=("user", "full_name"), mode="truncate", truncate_to=3))
    register_pii_rule(PIIRule(path=("credit_card",), mode="drop"))

    register_cardinality_limit("user_id", max_values=2, ttl_seconds=60)

    log.info(
        "example.policy.pii",
        user={"email": "dev@example.com", "full_name": "Casey Developer"},
        credit_card="4111111111111111",
        token=token_value,
    )

    metric = counter("example.policy.requests")
    for user_id in ("u1", "u2", "u3", "u4"):
        attrs = guard_attributes({"user_id": user_id})
        metric.add(1, attrs)
        print({"user_id": user_id, "guarded": attrs})

    shutdown_telemetry()


if __name__ == "__main__":
    main()
