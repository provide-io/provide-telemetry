#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import time

from provide.telemetry import ExporterPolicy, get_exporter_policy, get_health_snapshot, set_exporter_policy
from provide.telemetry.resilience import run_with_resilience


def main() -> None:
    set_exporter_policy("logs", ExporterPolicy(retries=1, backoff_seconds=0.0, fail_open=True))

    attempts = {"count": 0}

    def flaky_fail_open() -> str:
        attempts["count"] += 1
        raise RuntimeError("simulated exporter failure")

    result = run_with_resilience("logs", flaky_fail_open)
    print({"fail_open_result": result, "attempts": attempts["count"], "policy": get_exporter_policy("logs")})

    set_exporter_policy("logs", ExporterPolicy(retries=1, backoff_seconds=0.0, fail_open=False))

    attempts_closed = {"count": 0}

    def flaky_fail_closed() -> str:
        attempts_closed["count"] += 1
        raise RuntimeError("simulated hard failure")

    try:
        run_with_resilience("logs", flaky_fail_closed)
    except RuntimeError as exc:
        print({"fail_closed_error": str(exc), "attempts": attempts_closed["count"]})

    snapshot = get_health_snapshot()
    print(
        {
            "retries_logs": snapshot.retries_logs,
            "export_failures_logs": snapshot.export_failures_logs,
            "last_error_logs": snapshot.last_error_logs,
        }
    )


if __name__ == "__main__":
    main()
