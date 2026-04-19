#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Convert ``go test -bench`` text output into ``{operation, ns_per_op}`` JSON
lines suitable for piping into ``scripts/perf_check.py``.

Go's stable benchmark output line shape::

    BenchmarkEventName_3Segments-24  \t  1  \t  114709 ns/op  \t [extra ...]

The ``-NN`` suffix is GOMAXPROCS at the time of the run; we strip it so the
operation name is stable across runners with different CPU counts.
"""

from __future__ import annotations

import json
import re
import sys

# Captures: name (without -NN suffix), ns/op as a float.
_BENCH_LINE = re.compile(r"^(Benchmark\S+?)(?:-\d+)?\s+\d+\s+(\d+(?:\.\d+)?)\s+ns/op")


def main() -> int:
    emitted = 0
    for line in sys.stdin:
        match = _BENCH_LINE.match(line)
        if not match:
            continue
        op = match.group(1)
        ns_per_op = float(match.group(2))
        print(json.dumps({"operation": op, "ns_per_op": ns_per_op}))
        emitted += 1
    if emitted == 0:
        print("parse_go_bench: no benchmark lines decoded from stdin", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
