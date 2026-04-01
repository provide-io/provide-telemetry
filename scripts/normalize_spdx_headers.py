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


def normalize_headers(root: Path) -> list[Path]:
    from spdx_headers import find_python_files, normalize_python_text

    changed: list[Path] = []
    for path in find_python_files(root):
        original = path.read_text(encoding="utf-8")
        normalized = normalize_python_text(original)
        if normalized != original:
            path.write_text(normalized, encoding="utf-8")
            changed.append(path)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Python SPDX headers.")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    changed = normalize_headers(args.root.resolve())
    if changed:
        print(f"normalized SPDX headers in {len(changed)} file(s):")
        for path in changed:
            print(f"  {path}")
    else:
        print("all Python SPDX headers already normalized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
