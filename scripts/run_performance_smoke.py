#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from dataclasses import dataclass

from undef.telemetry import event_name
from undef.telemetry.backpressure import QueuePolicy, set_queue_policy
from undef.telemetry.health import get_health_snapshot
from undef.telemetry.logger.processors import sanitize_sensitive_fields
from undef.telemetry.metrics.fallback import Counter, Histogram
from undef.telemetry.sampling import SamplingPolicy, should_sample
from undef.telemetry.tracing.context import set_trace_context
from undef.telemetry.tracing.decorators import trace


@dataclass(frozen=True)
class PerfResult:
    event_name_ns: float
    should_sample_ns: float
    sanitize_ns: float
    trace_decorator_ns: float
    counter_add_ns: float
    histogram_record_ns: float
    health_snapshot_ns: float


def _bench_ns_per_op(iterations: int, fn: Callable[[], object]) -> float:
    # Run a tight loop and report average nanoseconds per call.
    start = time.perf_counter_ns()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter_ns() - start
    return elapsed / iterations


@trace("bench_noop")
def _traced_noop() -> None:
    pass


def run_benchmarks(iterations: int) -> PerfResult:
    policy = SamplingPolicy(default_rate=1.0)
    sanitize = sanitize_sensitive_fields(enabled=True)
    event_payload = {"password": "secret", "token": "abc", "request_id": "r1"}  # pragma: allowlist secret
    _ = policy  # Keep explicit policy object benchmark setup for future extension.

    # Setup for trace decorator benchmark
    set_trace_context("bench-trace", "bench-span")
    set_queue_policy(QueuePolicy())

    # Setup for metrics benchmark
    ctr = Counter("bench.counter")
    hist = Histogram("bench.histogram")

    event_name_ns = _bench_ns_per_op(iterations, lambda: event_name("auth", "login", "success"))
    should_sample_ns = _bench_ns_per_op(
        iterations,
        lambda: should_sample("logs", key="auth.login.success"),
    )
    sanitize_ns = _bench_ns_per_op(
        iterations,
        lambda: sanitize(None, "info", event_payload),
    )
    trace_decorator_ns = _bench_ns_per_op(
        iterations,
        _traced_noop,
    )
    counter_add_ns = _bench_ns_per_op(
        iterations,
        lambda: ctr.add(1),
    )
    histogram_record_ns = _bench_ns_per_op(
        iterations,
        lambda: hist.record(1.0),
    )
    health_snapshot_ns = _bench_ns_per_op(
        iterations,
        get_health_snapshot,
    )
    return PerfResult(
        event_name_ns=event_name_ns,
        should_sample_ns=should_sample_ns,
        sanitize_ns=sanitize_ns,
        trace_decorator_ns=trace_decorator_ns,
        counter_add_ns=counter_add_ns,
        histogram_record_ns=histogram_record_ns,
        health_snapshot_ns=health_snapshot_ns,
    )


def run_benchmarks_stable(iterations: int, runs: int) -> PerfResult:
    samples: list[PerfResult] = [run_benchmarks(iterations) for _ in range(max(1, runs))]
    return PerfResult(
        event_name_ns=float(median(sample.event_name_ns for sample in samples)),
        should_sample_ns=float(median(sample.should_sample_ns for sample in samples)),
        sanitize_ns=float(median(sample.sanitize_ns for sample in samples)),
        trace_decorator_ns=float(median(sample.trace_decorator_ns for sample in samples)),
        counter_add_ns=float(median(sample.counter_add_ns for sample in samples)),
        histogram_record_ns=float(median(sample.histogram_record_ns for sample in samples)),
        health_snapshot_ns=float(median(sample.health_snapshot_ns for sample in samples)),
    )


def evaluate_thresholds(
    result: PerfResult,
    max_event_name_ns: float,
    max_should_sample_ns: float,
    max_sanitize_ns: float,
    max_trace_decorator_ns: float,
    max_counter_add_ns: float,
    max_histogram_record_ns: float,
    max_health_snapshot_ns: float,
) -> list[str]:
    failures: list[str] = []
    checks = [
        ("event_name_ns", result.event_name_ns, max_event_name_ns),
        ("should_sample_ns", result.should_sample_ns, max_should_sample_ns),
        ("sanitize_ns", result.sanitize_ns, max_sanitize_ns),
        ("trace_decorator_ns", result.trace_decorator_ns, max_trace_decorator_ns),
        ("counter_add_ns", result.counter_add_ns, max_counter_add_ns),
        ("histogram_record_ns", result.histogram_record_ns, max_histogram_record_ns),
        ("health_snapshot_ns", result.health_snapshot_ns, max_health_snapshot_ns),
    ]
    for name, actual, threshold in checks:
        if actual > threshold:
            failures.append(f"{name} {actual:.2f} > {threshold:.2f}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a telemetry performance smoke benchmark.")
    parser.add_argument("--iterations", type=int, default=200_000, help="Loop iterations per benchmark.")
    parser.add_argument("--enforce", action="store_true", help="Fail if any configured threshold is exceeded.")
    parser.add_argument("--max-event-name-ns", type=float, default=2_500.0)
    parser.add_argument("--max-should-sample-ns", type=float, default=4_000.0)
    parser.add_argument("--max-sanitize-ns", type=float, default=6_500.0)
    parser.add_argument("--max-trace-decorator-ns", type=float, default=8_000.0)
    parser.add_argument("--max-counter-add-ns", type=float, default=6_000.0)
    parser.add_argument("--max-histogram-record-ns", type=float, default=6_000.0)
    parser.add_argument("--max-health-snapshot-ns", type=float, default=5_000.0)
    parser.add_argument(
        "--ci-threshold-multiplier",
        type=float,
        default=1.5,
        help="Multiplier applied to thresholds when CI environment is detected.",
    )
    args = parser.parse_args()

    result = run_benchmarks(args.iterations)
    print(
        {
            "iterations": args.iterations,
            "event_name_ns": round(result.event_name_ns, 2),
            "should_sample_ns": round(result.should_sample_ns, 2),
            "sanitize_ns": round(result.sanitize_ns, 2),
            "trace_decorator_ns": round(result.trace_decorator_ns, 2),
            "counter_add_ns": round(result.counter_add_ns, 2),
            "histogram_record_ns": round(result.histogram_record_ns, 2),
            "health_snapshot_ns": round(result.health_snapshot_ns, 2),
            "enforced": args.enforce,
        }
    )

    failures = evaluate_thresholds(
        result,
        max_event_name_ns=args.max_event_name_ns * threshold_multiplier,
        max_should_sample_ns=args.max_should_sample_ns * threshold_multiplier,
        max_sanitize_ns=args.max_sanitize_ns * threshold_multiplier,
        max_trace_decorator_ns=args.max_trace_decorator_ns * threshold_multiplier,
        max_counter_add_ns=args.max_counter_add_ns * threshold_multiplier,
        max_histogram_record_ns=args.max_histogram_record_ns * threshold_multiplier,
        max_health_snapshot_ns=args.max_health_snapshot_ns * threshold_multiplier,
    )
    if failures:
        print({"threshold_failures": failures})
        return 1 if args.enforce else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
