#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import argparse
import ast
import re
from collections.abc import Iterable
from pathlib import Path

_DEFAULT_EXCLUDE_PARTS = {
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "mutants",
    "build",
    "dist",
}
_SEG = r"[a-z][a-z0-9_]*"
_EVENT_RE = re.compile(rf"^{_SEG}(?:\.{_SEG})*$")
_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "trace"}
# Deliberate exemption marker for log calls whose first argument is not an
# event name (e.g. a stdlib-logging format string). Honored on the call line
# or on the string literal's own line.
_ALLOW_MARKER = "# event-literal: allow"


def _iter_python_files(roots: Iterable[Path], exclude_parts: set[str]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in exclude_parts for part in path.parts):
                continue
            if path.is_file():
                yield path


def _first_string_arg(node: ast.Call) -> tuple[str, int] | None:
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return (first.value, first.lineno)
    return None


def _has_allow_marker(lines: list[str], line_numbers: set[int]) -> bool:
    return any(_ALLOW_MARKER in lines[lineno - 1] for lineno in line_numbers if 0 < lineno <= len(lines))


def _is_log_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr in _LOG_METHODS


def find_event_literal_violations(roots: Iterable[Path], exclude_parts: set[str]) -> list[str]:
    violations: list[str] = []
    for path in sorted(_iter_python_files(roots, exclude_parts)):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_log_call(node):
                continue
            first_arg = _first_string_arg(node)
            if first_arg is None:
                continue
            literal, literal_lineno = first_arg
            if _EVENT_RE.match(literal):
                continue
            line = getattr(node, "lineno", 1)
            if _has_allow_marker(lines, {line, literal_lineno}):
                continue
            col = getattr(node, "col_offset", 0) + 1
            violations.append(f"{path}:{line}:{col}: invalid event literal: {literal!r}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate telemetry event-name string literals in log calls use valid segment format."
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        default=["src", "examples"],
        help="Directories to scan for Python files.",
    )
    parser.add_argument(
        "--exclude-part",
        action="append",
        default=[],
        help="Path component to exclude. Can be provided multiple times.",
    )
    args = parser.parse_args()

    roots = [Path(root) for root in args.roots]
    exclude_parts = set(_DEFAULT_EXCLUDE_PARTS)
    exclude_parts.update(args.exclude_part)
    violations = find_event_literal_violations(roots, exclude_parts)
    if not violations:
        print("Event literal check passed: all scanned log event literals use valid segment format.")
        return 0

    print(f"Event literal check failed: {len(violations)} invalid literal(s).")
    for item in violations:
        print(f"  {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
