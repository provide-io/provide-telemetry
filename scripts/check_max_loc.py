#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import argparse
import subprocess
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
    "bin",
    "obj",
    ".worktrees",
    ".claude",
    "coverage",
    "reports",
    ".stryker-tmp",
    "_secret_patterns_generated.py",  # generated file, intentionally large
}

# Polyglot scope: every source/test file across all languages must obey the
# same 777-LOC ceiling. The primary scan is `git ls-files`, so the scope is
# "every tracked file with one of these extensions or names" and cannot drift
# when a directory is added. DEFAULT_ROOTS is the fallback for a checkout
# without git (or an explicit --roots) and should name every directory that
# holds tracked source, so both scans agree.
DEFAULT_ROOTS = [
    "src",
    "tests",
    "scripts",
    "examples",
    "spec",
    "ci",
    "e2e",
    "infra",
    "typescript",
    "go",
    "rust/src",
    "rust/tests",
    "rust/examples",
    "rust/benches",
    "csharp/src",
    "csharp/tests",
    "csharp/probes",
    "csharp/consumer",
    "csharp/examples",
    "csharp/perf",
]
DEFAULT_EXTENSIONS = (".py", ".ts", ".go", ".rs", ".cs", ".sh", ".js", ".mjs", ".mts", ".tsx")
# Extension-less build files are code too.
DEFAULT_FILENAMES = ("Makefile", "Dockerfile")
DEFAULT_ALLOWLIST = Path(__file__).parent.parent / ".max_loc_allowlist.yaml"


def _is_excluded(path: Path) -> bool:
    return any(part in DEFAULT_EXCLUDE_PARTS for part in path.parts)


def _is_source_file(path: Path, extensions: tuple[str, ...], filenames: tuple[str, ...]) -> bool:
    return path.suffix in extensions or path.name in filenames


def _iter_source_files(
    roots: Iterable[Path],
    extensions: tuple[str, ...],
    filenames: tuple[str, ...] = (),
) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or not _is_source_file(path, extensions, filenames):
                continue
            if _is_excluded(path.relative_to(root)):
                continue
            yield path


def git_tracked_files(repo_root: Path) -> list[Path] | None:
    """Return every git-tracked file under *repo_root*, or None when git cannot answer.

    Tracked files are the honest scope for a source-size policy: generated
    trees (mutants.out, StrykerOutput, coverage) never enter it, and a new
    source directory is covered the day its first file is committed.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [repo_root / entry for entry in proc.stdout.decode("utf-8").split("\0") if entry]


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
    *,
    filenames: tuple[str, ...] = (),
    files: Iterable[Path] | None = None,
) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
    """Return (real offenders, allowlist-grandfathered files).

    A file appearing in the allowlist is exempt from the global cap but still
    capped at its allowlisted ceiling — this prevents grandfathered files from
    growing further while their split is pending.

    When *files* is given (normally the git-tracked list) it is the scan set and
    *roots* is ignored; otherwise *roots* are walked.
    """
    real_offenders: list[tuple[Path, int]] = []
    grandfathered: list[tuple[Path, int]] = []
    if files is None:
        candidates: Iterable[Path] = _iter_source_files(roots, extensions, filenames)
    else:
        candidates = (
            path
            for path in files
            if path.is_file() and _is_source_file(path, extensions, filenames) and not _is_excluded(path)
        )
    for path in sorted(candidates):
        lines = _line_count(path)
        if lines <= max_lines:
            continue
        try:
            rel_path = path.resolve().relative_to(repo_root.resolve())
        except ValueError:
            rel_path = path
        # Normalise to forward slashes so the allowlist file (cross-platform
        # YAML using POSIX separators) matches on Windows where Path stringifies
        # with backslashes.
        rel = rel_path.as_posix()
        ceiling = allowlist.get(rel)
        if ceiling is not None and lines <= ceiling:
            grandfathered.append((path, lines))
        else:
            real_offenders.append((path, lines))
    return real_offenders, grandfathered


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail if any source file exceeds a maximum line count.")
    parser.add_argument("--max-lines", type=int, default=777, help="Maximum allowed lines per source file.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=None,
        help="Directories to scan instead of the git-tracked file list (default: git ls-files, else DEFAULT_ROOTS).",
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=list(DEFAULT_EXTENSIONS),
        help="File extensions to check (with leading dot).",
    )
    parser.add_argument(
        "--filenames",
        nargs="+",
        default=list(DEFAULT_FILENAMES),
        help="Extension-less file names to check (e.g. Makefile).",
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
    extensions = tuple(args.extensions)
    filenames = tuple(args.filenames)
    allowlist = _load_allowlist(args.allowlist)
    tracked = None if args.roots else git_tracked_files(repo_root)
    root_names = args.roots or DEFAULT_ROOTS
    roots = [Path(root) if Path(root).is_absolute() else repo_root / root for root in root_names]
    offenders, grandfathered = find_loc_offenders(
        roots, args.max_lines, extensions, allowlist, repo_root, filenames=filenames, files=tracked
    )
    scope = "git-tracked files" if tracked is not None else f"{len(roots)} root(s)"

    if grandfathered:
        print(f"LOC check: {len(grandfathered)} grandfathered file(s) (allowlisted, must be split):")
        for path, lines in grandfathered:
            print(f"  {path}: {lines}")

    if not offenders:
        print(f"LOC check passed: no source file exceeds {args.max_lines} lines (excluding allowlist; scope: {scope}).")
        return 0

    print(f"LOC check failed: {len(offenders)} file(s) exceed {args.max_lines} lines without allowlist entry.")
    for path, lines in offenders:
        print(f"  {path}: {lines}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
