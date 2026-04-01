#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Error fingerprinting and session correlation demo.

Demonstrates:
- Error fingerprinting: stable hex fingerprint per exception type + call site
- Session correlation: bind a session ID that propagates across all log events
"""

from __future__ import annotations

import sys

from provide.telemetry import (
    bind_session_context,
    clear_session_context,
    get_logger,
    get_session_id,
    setup_telemetry,
    shutdown_telemetry,
)

# Private API — used here for demonstration purposes only.
from provide.telemetry.logger.processors import _compute_error_fingerprint, add_error_fingerprint


def _demo_error_fingerprint() -> None:
    print("--- Error Fingerprinting ---\n")

    # Same exception type without traceback produces the same fingerprint.
    fp_a = _compute_error_fingerprint("ValueError", None)
    fp_b = _compute_error_fingerprint("ValueError", None)
    print(f"  ValueError (no tb) fingerprint 1: {fp_a}")
    print(f"  ValueError (no tb) fingerprint 2: {fp_b}")
    print(f"  Same? {fp_a == fp_b}\n")

    # Different exception types produce different fingerprints.
    fp_c = _compute_error_fingerprint("TypeError", None)
    print(f"  TypeError  (no tb) fingerprint:   {fp_c}")
    print(f"  Differs from ValueError? {fp_a != fp_c}\n")

    # Using the processor on an event dict with exc_info.
    log = get_logger("examples.fingerprint")
    try:
        raise RuntimeError("simulated failure")
    except RuntimeError:
        exc_info = sys.exc_info()
        event = {"event": "app.error.simulated", "exc_info": exc_info}
        result = add_error_fingerprint(None, "", event)
        fp = result.get("error_fingerprint", "N/A")
        print(f"  RuntimeError with traceback fingerprint: {fp}")
        log.error("app.error.simulated", error_fingerprint=fp, exc_name="RuntimeError")

    # Normal events get no fingerprint.
    normal = {"event": "app.start.ok"}
    result = add_error_fingerprint(None, "", normal)
    print(f"  Normal event has fingerprint? {'error_fingerprint' in result}\n")


def _demo_session_correlation() -> None:
    print("--- Session Correlation ---\n")

    log = get_logger("examples.session")

    print(f"  Session before bind: {get_session_id()}")

    bind_session_context("sess-demo-42")
    print(f"  Session after bind:  {get_session_id()}")

    log.info("app.session.bound", msg="session is active")
    log.info("app.session.action", action="page_view", path="/dashboard")

    clear_session_context()
    print(f"  Session after clear: {get_session_id()}\n")


def main() -> None:
    print("Error Fingerprinting and Session Correlation Demo\n")

    setup_telemetry()

    _demo_error_fingerprint()
    _demo_session_correlation()

    print("Done!")
    shutdown_telemetry()


if __name__ == "__main__":
    main()
