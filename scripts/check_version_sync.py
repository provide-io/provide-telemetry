#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Check that all language packages share the same major.minor as VERSION.

VERSION file contains "MAJOR.MINOR" (e.g. "0.3").
Each language package version must start with that prefix.

Usage:
    python scripts/check_version_sync.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_version_file() -> str:
    """Read major.minor from VERSION."""
    return (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _python_version() -> str | None:
    """Read Python package version from pyproject.toml dynamic version pointer."""
    pyproject = _REPO_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return None
    text = pyproject.read_text(encoding="utf-8")
    if 'version = {file = "VERSION"}' in text:
        return _read_version_file()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _typescript_version() -> str | None:
    """Read version from typescript/package.json."""
    pkg = _REPO_ROOT / "typescript" / "package.json"
    if not pkg.exists():
        return None
    data = json.loads(pkg.read_text(encoding="utf-8"))
    return data.get("version")


def _go_version() -> str | None:
    """Read version from go/VERSION (future)."""
    go_version = _REPO_ROOT / "go" / "VERSION"
    if go_version.exists():
        return go_version.read_text(encoding="utf-8").strip()
    return None


def _rust_version() -> str | None:
    """Read version from rust/Cargo.toml."""
    cargo = _REPO_ROOT / "rust" / "Cargo.toml"
    if not cargo.exists():
        return None
    text = cargo.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _csharp_version() -> str | None:
    """Read version from csharp/src/Undef.Telemetry/*.csproj."""
    csproj_dir = _REPO_ROOT / "csharp" / "src" / "Undef.Telemetry"
    if not csproj_dir.exists():
        return None
    for csproj in csproj_dir.glob("*.csproj"):
        text = csproj.read_text(encoding="utf-8")
        match = re.search(r"<Version>([^<]+)</Version>", text)
        if match:
            return match.group(1)
    return None


_LANG_READERS = {
    "python": _python_version,
    "typescript": _typescript_version,
    "go": _go_version,
    "rust": _rust_version,
    "csharp": _csharp_version,
}


def main() -> int:
    """Check version sync. Returns 0 on success, 1 on mismatch."""
    canonical_raw = _read_version_file()
    canonical_parts = canonical_raw.split(".")
    canonical = f"{canonical_parts[0]}.{canonical_parts[1]}" if len(canonical_parts) >= 2 else canonical_raw
    print(f"VERSION file: {canonical_raw} (major.minor: {canonical})")

    errors: list[str] = []
    for lang, reader in _LANG_READERS.items():
        version = reader()
        if version is None:
            print(f"  {lang}: not present (skipped)")
            continue
        parts = version.split(".")
        lang_major_minor = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else version

        if lang_major_minor == canonical:
            print(f"  {lang}: {version} — OK")
        else:
            print(f"  {lang}: {version} — MISMATCH (expected {canonical}.*)")
            errors.append(f"{lang} version {version} does not match {canonical}")

    if errors:
        print(f"\nFAILED — {len(errors)} version mismatches.")
        return 1

    print("\nPASSED — all present languages match VERSION.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
