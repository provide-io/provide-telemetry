#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

import yaml

DEFAULT_EXCLUDE_PARTS = {
    ".venv",
    ".venv-test",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "mutants",
    "build",
    "dist",
    "node_modules",
    "target",
    ".worktrees",
    ".claude",
    "_secret_patterns_generated.py",  # generated file, intentionally large
}

# Polyglot scope: every source/test file across all four languages must
# obey the same 500-LOC ceiling. New violations are blocked at commit time.
DEFAULT_ROOTS = [
    "src",
    "tests",
    "scripts",
    "examples",
    "spec",
    "ci",
    "typescript/src",
    "typescript/tests",
    "go",
    "rust/src",
    "rust/tests",
    "rust/examples",
]
DEFAULT_EXTENSIONS = (".py", ".ts", ".go", ".rs")
DEFAULT_ALLOWLIST = Path(__file__).parent.parent / ".max_loc_allowlist.yaml"


def _is_excluded(path: Path) -> bool:
    return any(part in DEFAULT_EXCLUDE_PARTS for part in path.parts)


def _iter_source_files(roots: Iterable[Path], extensions: tuple[str, ...]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for ext in extensions:
            for path in root.rglob(f"*{ext}"):
                if _is_excluded(path):
                    continue
                if path.is_file():
                    yield path


def _line_count(path: Path) -> int:
    # Count physical lines to enforce a hard size cap.
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _load_allowlist(path: Path) -> dict[str, int]:
    """Parse the allowlist YAML and return a {relpath: max_lines} map.

    Each entry is a temporary exemption granted because the file already
    exceeds the limit. New code MUST stay under the limit. Entries should be
    removed as files are split or shrunk.
    """
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("allowlist") or []
    result: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rel = entry.get("path")
        ceiling = entry.get("ceiling")
        if isinstance(rel, str) and isinstance(ceiling, int):
            result[rel] = ceiling
    return result


def find_loc_offenders(
    roots: Iterable[Path],
    max_lines: int,
    extensions: tuple[str, ...],
    allowlist: dict[str, int],
    repo_root: Path,
) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
    """Return (real offenders, allowlist-grandfathered files).

    A file appearing in the allowlist is exempt from the global cap but still
    capped at its allowlisted ceiling — this prevents grandfathered files from
    growing further while their split is pending.
    """
    real_offenders: list[tuple[Path, int]] = []
    grandfathered: list[tuple[Path, int]] = []
    for path in sorted(_iter_source_files(roots, extensions)):
        lines = _line_count(path)
        if lines <= max_lines:
            continue
        try:
            rel = str(path.resolve().relative_to(repo_root.resolve()))
        except ValueError:
            rel = str(path)
        ceiling = allowlist.get(rel)
        if ceiling is not None and lines <= ceiling:
            grandfathered.append((path, lines))
        else:
            real_offenders.append((path, lines))
    return real_offenders, grandfathered


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail if any source file exceeds a maximum line count.")
    parser.add_argument("--max-lines", type=int, default=500, help="Maximum allowed lines per source file.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=DEFAULT_ROOTS,
        help="Directories to scan for source files.",
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=list(DEFAULT_EXTENSIONS),
        help="File extensions to check (with leading dot).",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help="YAML allowlist of grandfathered violators (each with a ceiling).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent
    # Anchor relative roots to the repo so the gate scans the same tree
    # regardless of the caller's cwd. Without this, invoking the script
    # from outside the repo silently passes (no roots exist).
    roots = [Path(root) if Path(root).is_absolute() else repo_root / root for root in args.roots]
    extensions = tuple(args.extensions)
    allowlist = _load_allowlist(args.allowlist)
    offenders, grandfathered = find_loc_offenders(roots, args.max_lines, extensions, allowlist, repo_root)

    if grandfathered:
        print(f"LOC check: {len(grandfathered)} grandfathered file(s) (allowlisted, must be split):")
        for path, lines in grandfathered:
            print(f"  {path}: {lines}")

    if not offenders:
        print(f"LOC check passed: no source file exceeds {args.max_lines} lines (excluding allowlist).")
        return 0

    print(f"LOC check failed: {len(offenders)} file(s) exceed {args.max_lines} lines without allowlist entry.")
    for path, lines in offenders:
        print(f"  {path}: {lines}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
