#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

DEFAULT_EXCLUDE_PARTS = {
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "mutants",
    "build",
    "dist",
}


def _iter_python_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in DEFAULT_EXCLUDE_PARTS for part in path.parts):
                continue
            if path.is_file():
                yield path


def _line_count(path: Path) -> int:
    # Count physical lines to enforce a hard size cap.
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def find_loc_offenders(roots: Iterable[Path], max_lines: int) -> list[tuple[Path, int]]:
    offenders: list[tuple[Path, int]] = []
    for path in sorted(_iter_python_files(roots)):
        lines = _line_count(path)
        if lines > max_lines:
            offenders.append((path, lines))
    return offenders


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail if any Python file exceeds a maximum line count.")
    parser.add_argument("--max-lines", type=int, default=500, help="Maximum allowed lines per .py file.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=["src", "tests", "scripts", "examples"],
        help="Directories to scan for Python files.",
    )
    args = parser.parse_args()

    roots = [Path(root) for root in args.roots]
    offenders = find_loc_offenders(roots, args.max_lines)
    if not offenders:
        print(f"LOC check passed: no Python file exceeds {args.max_lines} lines.")
        return 0

    print(f"LOC check failed: {len(offenders)} file(s) exceed {args.max_lines} lines.")
    for path, lines in offenders:
        print(f"  {path}: {lines}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
