#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Convert ``cargo bench`` (criterion) text output into ``{operation, ns_per_op}``
JSON lines suitable for piping into ``scripts/perf_check.py``.

Criterion in --quick mode prints one summary line per benchmark::

    should_sample_logs      time:   [13.514 ns 13.522 ns 13.552 ns]
    sanitize_payload        time:   [1.0256 µs 1.0306 µs 1.0508 µs]

We extract the median (middle of the three values) and convert to ns. Units
seen in practice: ns, µs (or us), ms, s. Anything else is ignored with a
stderr warning so an unsupported unit is visible rather than silent.
"""

from __future__ import annotations

import json
import re
import sys

_UNIT_TO_NS = {
    "ns": 1.0,
    "us": 1_000.0,
    "ms": 1_000_000.0,
    "s": 1_000_000_000.0,
}


def _normalize_unit(unit: str) -> str:
    """Map any micro-prefix codepoint to ASCII ``u`` so the dict lookup is
    encoding-independent. Criterion emits U+00B5 (MICRO SIGN); some shells
    or terminals re-encode to U+03BC (GREEK SMALL LETTER MU); CP1252-era
    pipelines may produce yet another representation. Collapsing to ``u``
    sidesteps all of that.
    """
    return unit.replace("\u00b5", "u").replace("\u03bc", "u")


_LINE = re.compile(
    r"^(\S+)\s+time:\s+\[\s*"
    r"\d+(?:\.\d+)?\s+\S+\s+"  # low — ignored
    r"(\d+(?:\.\d+)?)\s+(\S+)\s+"  # median + unit
    r"\d+(?:\.\d+)?\s+\S+\s*\]"  # high — ignored
)


def main() -> int:
    # Read stdin tolerantly — some Windows runners pipe raw CP1252 bytes for
    # the micro sign even though Python expects UTF-8 by default. errors=replace
    # keeps the unit-normalization step working regardless of the source encoding.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    emitted = 0
    for line in sys.stdin:
        match = _LINE.match(line)
        if not match:
            continue
        op, value, raw_unit = match.group(1), float(match.group(2)), match.group(3)
        unit = _normalize_unit(raw_unit)
        scale = _UNIT_TO_NS.get(unit)
        if scale is None:
            print(f"parse_criterion: unknown time unit {raw_unit!r} for {op!r}", file=sys.stderr)
            continue
        ns_per_op = value * scale
        print(json.dumps({"operation": op, "ns_per_op": ns_per_op}))
        emitted += 1
    if emitted == 0:
        print("parse_criterion: no benchmark lines decoded from stdin", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
