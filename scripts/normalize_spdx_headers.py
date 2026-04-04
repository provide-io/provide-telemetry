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

_GO_COPYRIGHT = "// SPDX-FileCopyrightText" + ": Copyright (C) 2026 provide.io llc\n"
_GO_LICENSE = "// SPDX-License-Identifier" + ": Apache-2.0\n"
_GO_CANONICAL_BLOCK = (_GO_COPYRIGHT, _GO_LICENSE)


def _has_go_spdx_header(text: str) -> bool:
    """Return True if the Go file begins with the canonical // SPDX header block."""
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        return False
    return lines[0] == _GO_COPYRIGHT and lines[1] == _GO_LICENSE


def _normalize_go_text(text: str) -> str:
    """Return text with the canonical Go SPDX header prepended (stripping any existing SPDX lines)."""
    lines = text.splitlines(keepends=True)
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("// SPDX-") or line.strip() == "":
            idx += 1
            continue
        break
    body = "".join(lines[idx:])
    return "".join(_GO_CANONICAL_BLOCK) + body


def normalize_headers(root: Path) -> list[Path]:
    from spdx_headers import EXCLUDED_DIRS as _BASE_EXCLUDED_DIRS
    from spdx_headers import find_python_files, normalize_python_text

    excluded_dirs = _BASE_EXCLUDED_DIRS | {"vendor"}

    changed: list[Path] = []
    for path in find_python_files(root):
        original = path.read_text(encoding="utf-8")
        normalized = normalize_python_text(original)
        if normalized != original:
            path.write_text(normalized, encoding="utf-8")
            changed.append(path)

    for path in root.rglob("*.go"):
        if any(part in excluded_dirs for part in path.parts):
            continue
        original = path.read_text(encoding="utf-8")
        if not _has_go_spdx_header(original):
            normalized = _normalize_go_text(original)
            path.write_text(normalized, encoding="utf-8")
            changed.append(path)

    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Python and Go SPDX headers.")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    changed = normalize_headers(args.root.resolve())
    if changed:
        print(f"normalized SPDX headers in {len(changed)} file(s):")
        for path in changed:
            print(f"  {path}")
    else:
        print("all Python and Go SPDX headers already normalized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
