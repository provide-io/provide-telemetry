#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from spdx_headers import EXCLUDED_DIRS as _BASE_EXCLUDED_DIRS  # noqa: E402
from spdx_headers import has_go_canonical_header as _has_go_spdx_header  # noqa: E402

_EXCLUDED_DIRS = _BASE_EXCLUDED_DIRS | {"vendor"}


def _find_go_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.go"):
        if any(part in _EXCLUDED_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def find_noncompliant_files(root: Path) -> list[Path]:
    from spdx_headers import find_python_files, has_canonical_header

    noncompliant: list[Path] = []
    for path in find_python_files(root):
        text = path.read_text(encoding="utf-8")
        if not has_canonical_header(text):
            noncompliant.append(path)
    for path in _find_go_files(root):
        text = path.read_text(encoding="utf-8")
        if not _has_go_spdx_header(text):
            noncompliant.append(path)
    return noncompliant


def main() -> int:
    parser = argparse.ArgumentParser(description="Check canonical SPDX headers (Python + Go).")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    offenders = find_noncompliant_files(args.root.resolve())
    if offenders:
        print(f"SPDX header check failed: {len(offenders)} file(s) are noncompliant.")
        for path in offenders:
            print(f"  {path}")
        print("Run: uv run python scripts/normalize_spdx_headers.py")
        return 1
    print("SPDX header check passed: all Python and Go files are compliant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
