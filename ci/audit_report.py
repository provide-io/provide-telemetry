# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Shared assertions for the dependency-vulnerability gates.

Every ecosystem's scanner can succeed while having examined nothing — a lockfile
that failed to export, a solution that restored no projects, a registry that
returned an empty graph. That is indistinguishable from a clean scan in the exit
code, so the gates assert an inventory floor of their own.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    """One vulnerability report, normalised across ecosystems."""

    package: str
    installed: str
    advisory: str
    severity: str
    fixed_in: str


def assert_non_empty_inventory(count: int, *, ecosystem: str, minimum: int) -> None:
    """Exit non-zero when the scanner examined implausibly few packages."""
    if count < minimum:
        print(
            f"{ecosystem}: dependency audit inventoried {count} packages, "
            f"expected at least {minimum}. A scan that sees nothing is a broken "
            f"scan, not a clean one.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def fail_on_findings(findings: list[Finding], *, ecosystem: str) -> int:
    """Print every finding and return the process exit code."""
    if not findings:
        print(f"{ecosystem}: dependency audit clean")
        return 0
    print(f"{ecosystem}: {len(findings)} vulnerable package(s)", file=sys.stderr)
    for finding in findings:
        print(
            f"  - {finding.package} {finding.installed}: {finding.advisory} "
            f"({finding.severity}); fixed in {finding.fixed_in}",
            file=sys.stderr,
        )
    return 1
