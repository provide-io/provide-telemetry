#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Fail on a RustSec advisory exception that is expired, undated, or unexplained.

A RustSec advisory can land on a transitive dependency with no patched release
for weeks, so `rust/deny.toml` can carry a temporary exception. An exception
with no expiry is a permanent silent downgrade of the gate, which is why the
expiry is mandatory and checked here rather than trusted to review.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path

_REPO_ROOT = Path(os.environ.get("PROVIDE_REPO_ROOT", Path(__file__).resolve().parent.parent))
_DENY_PATH = _REPO_ROOT / "rust" / "deny.toml"
_MAX_HORIZON_DAYS = 90


def validate(config: Mapping[str, object], today: dt.date) -> list[str]:
    """Return one error string per unacceptable exception entry."""
    # `or {}` would be wrong here: an empty list is falsy, so a malformed
    # `advisories = []` would be silently treated as an absent section and the
    # gate would report clean on a file it could not understand.
    advisories = config.get("advisories", {})
    if not isinstance(advisories, dict):
        return ["deny.toml: [advisories] must be a table"]
    entries = advisories.get("ignore", [])
    if not isinstance(entries, list):
        return ["deny.toml: [advisories].ignore must be an array"]

    errors: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"deny.toml: ignore entry must be a table, got {entry!r}")
            continue
        identifier = entry.get("id", "<no id>")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{identifier}: missing reason — say why this is accepted")
        raw_expiry = entry.get("expires")
        if not isinstance(raw_expiry, str) or not raw_expiry:
            errors.append(f"{identifier}: missing expires — an exception without an expiry is permanent")
            continue
        try:
            expires = dt.date.fromisoformat(raw_expiry)
        except ValueError:
            errors.append(f"{identifier}: expires {raw_expiry!r} is not an ISO date")
            continue
        if expires < today:
            errors.append(f"{identifier}: expired on {expires.isoformat()} — re-review or remove it")
        elif (expires - today).days > _MAX_HORIZON_DAYS:
            errors.append(f"{identifier}: expires {expires.isoformat()}, more than 90 days out")
    return errors


def main() -> int:
    if not _DENY_PATH.is_file():
        print(f"{_DENY_PATH} not found", file=sys.stderr)
        return 1
    config = tomllib.loads(_DENY_PATH.read_text(encoding="utf-8"))
    errors = validate(config, dt.date.today())
    if errors:
        print("Advisory exception gate failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Advisory exception gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
