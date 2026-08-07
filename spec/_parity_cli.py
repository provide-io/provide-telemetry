#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Command-line surface for the behavioral parity runner.

Split out of run_behavioral_parity.py to keep that module under the repo's
500-line ceiling; the parser is the only thing here.
"""

from __future__ import annotations

import argparse


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lang",
        default="python,typescript,go,rust,csharp",
        help="Comma-separated list of languages to check (default: all five)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds before a single language run is considered timed out (default: 300)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print full test output for failing languages",
    )
    parser.add_argument(
        "--skip-output",
        action="store_true",
        default=False,
        help="Skip log-output probes (default: probes are run)",
    )
    parser.add_argument(
        "--skip-contracts",
        action="store_true",
        default=False,
        help="Skip contract probe DSL cases (default: cases are run)",
    )
    # Strictness is the default, not a mode. A gate that downgrades an absent
    # toolchain to "skip" reports success for a language it never ran, which is
    # exactly the failure this script exists to prevent. --strict is accepted so
    # the documented CI invocation keeps working, and is a no-op.
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Accepted for compatibility; strictness is already the default",
    )
    parser.add_argument(
        "--allow-missing-runtimes",
        action="store_true",
        default=False,
        help=(
            "Downgrade an absent toolchain from a failure to a skip. "
            "For local work without all five SDKs installed — never in CI."
        ),
    )
    return parser
