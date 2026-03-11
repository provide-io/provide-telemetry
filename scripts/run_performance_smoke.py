#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from statistics import median

from undef.telemetry import event_name
from undef.telemetry.logger.processors import sanitize_sensitive_fields
from undef.telemetry.sampling import SamplingPolicy, should_sample


@dataclass(frozen=True)
class PerfResult:
    event_name_ns: float
    should_sample_ns: float
    sanitize_ns: float


def _bench_ns_per_op(iterations: int, fn: Callable[[], object]) -> float:
    # Run a tight loop and report average nanoseconds per call.
    start = time.perf_counter_ns()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter_ns() - start
    return elapsed / iterations


def run_benchmarks(iterations: int) -> PerfResult:
    policy = SamplingPolicy(default_rate=1.0)
    sanitize = sanitize_sensitive_fields(enabled=True)
    event_payload = {"password": "secret", "token": "abc", "request_id": "r1"}  # pragma: allowlist secret
    _ = policy  # Keep explicit policy object benchmark setup for future extension.

    event_name_ns = _bench_ns_per_op(iterations, lambda: event_name("auth", "login", "success"))
    should_sample_ns = _bench_ns_per_op(
        iterations,
        lambda: should_sample("logs", key="auth.login.success"),
    )
    sanitize_ns = _bench_ns_per_op(
        iterations,
        lambda: sanitize(None, "info", event_payload),
    )
    return PerfResult(
        event_name_ns=event_name_ns,
        should_sample_ns=should_sample_ns,
        sanitize_ns=sanitize_ns,
    )


def run_benchmarks_stable(iterations: int, runs: int) -> PerfResult:
    samples: list[PerfResult] = [run_benchmarks(iterations) for _ in range(max(1, runs))]
    return PerfResult(
        event_name_ns=float(median(sample.event_name_ns for sample in samples)),
        should_sample_ns=float(median(sample.should_sample_ns for sample in samples)),
        sanitize_ns=float(median(sample.sanitize_ns for sample in samples)),
    )


def evaluate_thresholds(
    result: PerfResult,
    max_event_name_ns: float,
    max_should_sample_ns: float,
    max_sanitize_ns: float,
) -> list[str]:
    failures: list[str] = []
    if result.event_name_ns > max_event_name_ns:
        failures.append(f"event_name_ns {result.event_name_ns:.2f} > {max_event_name_ns:.2f}")
    if result.should_sample_ns > max_should_sample_ns:
        failures.append(f"should_sample_ns {result.should_sample_ns:.2f} > {max_should_sample_ns:.2f}")
    if result.sanitize_ns > max_sanitize_ns:
        failures.append(f"sanitize_ns {result.sanitize_ns:.2f} > {max_sanitize_ns:.2f}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a telemetry performance smoke benchmark.")
    parser.add_argument("--iterations", type=int, default=200_000, help="Loop iterations per benchmark.")
    parser.add_argument("--runs", type=int, default=1, help="Number of repeated benchmark runs; median is evaluated.")
    parser.add_argument("--enforce", action="store_true", help="Fail if any configured threshold is exceeded.")
    parser.add_argument("--max-event-name-ns", type=float, default=2_500.0)
    parser.add_argument("--max-should-sample-ns", type=float, default=4_000.0)
    parser.add_argument("--max-sanitize-ns", type=float, default=6_500.0)
    parser.add_argument(
        "--ci-threshold-multiplier",
        type=float,
        default=1.5,
        help="Multiplier applied to thresholds when CI environment is detected.",
    )
    args = parser.parse_args()

    result = run_benchmarks_stable(args.iterations, args.runs)
    ci_detected = bool(os.getenv("CI"))
    threshold_multiplier = args.ci_threshold_multiplier if ci_detected else 1.0
    print(
        {
            "iterations": args.iterations,
            "runs": args.runs,
            "event_name_ns": round(result.event_name_ns, 2),
            "should_sample_ns": round(result.should_sample_ns, 2),
            "sanitize_ns": round(result.sanitize_ns, 2),
            "enforced": args.enforce,
            "ci_detected": ci_detected,
            "threshold_multiplier": threshold_multiplier,
        }
    )

    failures = evaluate_thresholds(
        result,
        max_event_name_ns=args.max_event_name_ns * threshold_multiplier,
        max_should_sample_ns=args.max_should_sample_ns * threshold_multiplier,
        max_sanitize_ns=args.max_sanitize_ns * threshold_multiplier,
    )
    if failures:
        print({"threshold_failures": failures})
        return 1 if args.enforce else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
