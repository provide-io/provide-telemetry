#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Assert what the collector actually received, not just that a name appeared.

``verify-collector-signals.sh`` greps the collector's debug log for signal
names. That proves something with the right name arrived and nothing more: a
record carrying the wrong service, no trace correlation, or leaking internal
library state passes it unchanged.

This checks the payload:

* the service resource attribute matches what the probe configured, so records
  are attributable to the right service rather than an SDK default;
* exported log records carry native OTLP ``Trace ID`` / ``Span ID`` — not merely
  a stringified copy in the attributes — because that is what makes a backend
  able to pivot from a log to its trace;
* no attribute begins with the library's internal prefix. Python was exporting
  ``__provide_telemetry_backpressure_ticket__`` on every record: the ticket is
  attached to the stdlib LogRecord so the handler boundary can release it, and
  OTel's handler turns record extras into OTLP attributes.

Usage: ci/verify-collector-content.py <collector.log> <expected-service-name>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Internal LogRecord fields are prefixed with this; none may reach an exporter.
_INTERNAL_PREFIX = "__provide_telemetry"

_ZERO_TRACE = "0" * 32
_ZERO_SPAN = "0" * 16

_ATTR_RE = re.compile(r"^\s*->\s*([^:]+):")
_TRACE_RE = re.compile(r"^Trace ID: ([0-9a-f]+)\s*$")
_SPAN_RE = re.compile(r"^Span ID: ([0-9a-f]+)\s*$")


def _fail(problems: list[str]) -> int:
    print("verify-collector-content: FAILED", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


def check(log_text: str, service: str) -> list[str]:
    """Return a list of problems; empty means the payload is sound."""
    problems: list[str] = []

    if f"service.name: Str({service})" not in log_text:
        problems.append(f"no resource carries service.name={service!r}; records would be attributed to an SDK default")

    leaked = sorted(
        {
            match.group(1).strip()
            for line in log_text.splitlines()
            if (match := _ATTR_RE.match(line)) and match.group(1).strip().startswith(_INTERNAL_PREFIX)
        }
    )
    for key in leaked:
        problems.append(f"internal library state exported as an OTLP attribute: {key}")

    # Log records are the block that starts at a "Body:" line and runs to the
    # next one. A fixed-size window is wrong here: the number of attribute lines
    # before Trace ID varies by language — TypeScript emits about ten, Python
    # none — so a short window reports a correlated record as uncorrelated.
    lines = log_text.splitlines()
    body_starts = [index for index, line in enumerate(lines) if line.startswith("Body: Str(")]
    correlated = 0
    for position, index in enumerate(body_starts):
        end = body_starts[position + 1] if position + 1 < len(body_starts) else len(lines)
        block = lines[index:end]
        trace_ids = [m.group(1) for candidate in block if (m := _TRACE_RE.match(candidate))]
        span_ids = [m.group(1) for candidate in block if (m := _SPAN_RE.match(candidate))]
        if not trace_ids or not span_ids:
            continue
        if trace_ids[0] != _ZERO_TRACE and span_ids[0] != _ZERO_SPAN:
            correlated += 1

    if correlated == 0:
        problems.append(
            "no exported log record carries a non-zero native Trace ID and Span ID; "
            "a backend cannot pivot from these logs to their traces"
        )

    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: verify-collector-content.py <collector.log> <expected-service-name>", file=sys.stderr)
        return 2

    log_path = Path(argv[1])
    if not log_path.is_file():
        print(f"verify-collector-content: {log_path} not found", file=sys.stderr)
        return 2

    problems = check(log_path.read_text(encoding="utf-8", errors="replace"), argv[2])
    if problems:
        return _fail(problems)

    print(f"verify-collector-content: OK — service, trace correlation and attribute hygiene verified in {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
