#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Memray stress test for sampling decision hot path."""

from __future__ import annotations

from undef.telemetry.sampling import (
    SamplingPolicy,
    get_sampling_policy,
    set_sampling_policy,
    should_sample,
)

SIGNALS = ("logs", "traces", "metrics")
KEYS = ("auth.login.success", "api.request.complete", "ws.message.received", None)


def main() -> None:
    """Run sampling stress cycles."""
    # Configure overrides for realistic workload
    set_sampling_policy(
        "logs",
        SamplingPolicy(
            default_rate=1.0,
            overrides={"auth.login.success": 0.5, "api.request.complete": 0.8},
        ),
    )

    # should_sample: 500K cycles with key lookups
    for _ in range(500_000):
        for key in KEYS:
            should_sample("logs", key=key)

    # should_sample across signals: 200K cycles
    for _ in range(200_000):
        for sig in SIGNALS:
            should_sample(sig)

    # get/set policy interleave: 100K cycles
    policy = SamplingPolicy(default_rate=0.9, overrides={"test.key": 0.7})
    for _ in range(100_000):
        for sig in SIGNALS:
            set_sampling_policy(sig, policy)
            get_sampling_policy(sig)


if __name__ == "__main__":
    main()
