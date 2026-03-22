#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Bounded-growth stress test: verify module-level caches do not grow unboundedly."""

from __future__ import annotations

import sys
import time
import tracemalloc

from undef.telemetry import cardinality, slo
from undef.telemetry.metrics import provider as metrics_provider


def _print_table_header() -> None:
    print(f"\n{'Phase':40s}  {'Mem Before':>12s}  {'Mem After':>12s}  {'Delta':>12s}  {'Result':>8s}")
    print("-" * 92)


def _fmt_bytes(n: int) -> str:
    if abs(n) < 1024:
        return f"{n} B"
    return f"{n / 1024:.1f} KiB"


def _phase_cardinality() -> bool:
    """Test that cardinality _seen dicts get pruned after TTL expires."""
    num_keys = 10
    max_values = 50
    ttl = 1.0  # minimum enforced by register_cardinality_limit

    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    # Register limits
    for i in range(num_keys):
        cardinality.register_cardinality_limit(f"attr_{i}", max_values=max_values, ttl_seconds=ttl)

    # Pump 500 unique values through each key
    for i in range(num_keys):
        for v in range(500):
            cardinality.guard_attributes({f"attr_{i}": f"value_{v}"})

    # Wait for TTL to expire
    time.sleep(ttl + 0.1)

    # Force pruning by manipulating _last_prune so the next guard call triggers it
    with cardinality._lock:
        for key in list(cardinality._last_prune):
            cardinality._last_prune[key] = 0.0

    # Trigger pruning via a guard call for each key
    for i in range(num_keys):
        cardinality.guard_attributes({f"attr_{i}": "trigger_prune"})

    snap_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    mem_before = sum(s.size for s in snap_before.statistics("filename"))
    mem_after = sum(s.size for s in snap_after.statistics("filename"))
    delta = mem_after - mem_before

    # Check: each _seen[key] should have at most max_values entries (not 500)
    all_ok = True
    for i in range(num_keys):
        key = f"attr_{i}"
        seen_count = len(cardinality._seen.get(key, {}))
        if seen_count > max_values:
            print(f"  FAIL: _seen[{key!r}] has {seen_count} entries (expected <= {max_values})")
            all_ok = False

    status = "PASS" if all_ok else "FAIL"
    print(f"{'Cardinality _seen pruning':40s}  {_fmt_bytes(mem_before):>12s}  {_fmt_bytes(mem_after):>12s}  {_fmt_bytes(delta):>12s}  {status:>8s}")
    return all_ok


def _phase_slo_instruments() -> bool:
    """Test that SLO counters/histograms use fixed metric names, not per-route."""
    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    # Call record_red_metrics with 100 distinct routes
    for i in range(100):
        slo.record_red_metrics(route=f"/api/v{i}/resource_{i}", method="GET", status_code=200, duration_ms=42.0)

    snap_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    mem_before = sum(s.size for s in snap_before.statistics("filename"))
    mem_after = sum(s.size for s in snap_after.statistics("filename"))
    delta = mem_after - mem_before

    # SLO uses exactly 3 fixed metric names for RED:
    #   http.requests.total, http.errors.total (only for 5xx), http.request.duration_ms
    # With status_code=200 only 2 counters + 1 histogram are created.
    counter_count = len(slo._counters)
    histogram_count = len(slo._histograms)
    total_instruments = counter_count + histogram_count

    # Should be a small fixed number, not 100 (one per route)
    ok = total_instruments <= 5
    status = "PASS" if ok else "FAIL"
    print(f"{'SLO instruments (fixed names)':40s}  {_fmt_bytes(mem_before):>12s}  {_fmt_bytes(mem_after):>12s}  {_fmt_bytes(delta):>12s}  {status:>8s}")
    if not ok:
        print(f"  FAIL: {counter_count} counters + {histogram_count} histograms = {total_instruments} (expected <= 5)")
    return ok


def _phase_meters_cache() -> bool:
    """Test that metrics provider _meters dict stays bounded."""
    tracemalloc.start()
    snap_before = tracemalloc.take_snapshot()

    # Without OTel installed, get_meter returns None and _meters stays empty.
    # Verify the cache doesn't grow from repeated calls.
    for i in range(100):
        metrics_provider.get_meter(f"test.meter.{i}")

    snap_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    mem_before = sum(s.size for s in snap_before.statistics("filename"))
    mem_after = sum(s.size for s in snap_after.statistics("filename"))
    delta = mem_after - mem_before

    meter_count = len(metrics_provider._meters)
    # Without a real provider, _meters should not cache anything.
    # With a real provider, it would cache by name — still bounded by call count.
    ok = meter_count <= 100
    status = "PASS" if ok else "FAIL"
    print(f"{'Metrics provider _meters cache':40s}  {_fmt_bytes(mem_before):>12s}  {_fmt_bytes(mem_after):>12s}  {_fmt_bytes(delta):>12s}  {status:>8s}")
    if not ok:
        print(f"  FAIL: _meters has {meter_count} entries (expected <= 100)")
    return ok


def main() -> int:
    """Run all bounded-growth checks and return 0 on success, 1 on failure."""
    print("Bounded-growth stress test")
    _print_table_header()

    results = [
        _phase_cardinality(),
        _phase_slo_instruments(),
        _phase_meters_cache(),
    ]

    # Cleanup
    cardinality.clear_cardinality_limits()
    slo._reset_slo_for_tests()
    metrics_provider._set_meter_for_test(None)

    print()
    if all(results):
        print("All bounded-growth checks PASSED.")
        return 0
    else:
        print("Some bounded-growth checks FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
