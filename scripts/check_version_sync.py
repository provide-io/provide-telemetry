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
    if re.search(r'version\s*=\s*\{\s*file\s*=\s*"VERSION"\s*\}', text):
        return _read_version_file()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _typescript_package_version() -> str | None:
    """Read version from typescript/package.json."""
    pkg = _REPO_ROOT / "typescript" / "package.json"
    if not pkg.exists():
        return None
    data = json.loads(pkg.read_text(encoding="utf-8"))
    return data.get("version")


def _typescript_runtime_version() -> str | None:
    """Read the exported runtime version from typescript/src/config.ts."""
    config = _REPO_ROOT / "typescript" / "src" / "config.ts"
    if not config.exists():
        return None
    text = config.read_text(encoding="utf-8")
    match = re.search(r"export const version = ['\"]([^'\"]+)['\"]", text)
    return match.group(1) if match else None


def _typescript_lockfile_version() -> str | None:
    """Read the package version stored in typescript/package-lock.json."""
    lockfile = _REPO_ROOT / "typescript" / "package-lock.json"
    if not lockfile.exists():
        return None
    data = json.loads(lockfile.read_text(encoding="utf-8"))
    top_level = data.get("version")
    if isinstance(top_level, str):
        return top_level
    packages = data.get("packages", {})
    if isinstance(packages, dict):
        root_package = packages.get("", {})
        if isinstance(root_package, dict):
            version = root_package.get("version")
            if isinstance(version, str):
                return version
    return None


def _go_version() -> str | None:
    """Read version from go/VERSION."""
    go_version = _REPO_ROOT / "go" / "VERSION"
    if go_version.exists():
        return go_version.read_text(encoding="utf-8").strip()
    return None


def _go_otel_version() -> str | None:
    """Read version from go/otel/VERSION."""
    v = _REPO_ROOT / "go" / "otel" / "VERSION"
    if v.exists():
        return v.read_text(encoding="utf-8").strip()
    return None


def _go_required_version(go_mod_path: Path, module_path: str) -> str | None:
    """Read a required module version from a go.mod file."""
    if not go_mod_path.exists():
        return None

    in_require_block = False
    for raw_line in go_mod_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if not line:
            continue

        if line == "require (":
            in_require_block = True
            continue
        if in_require_block and line == ")":
            in_require_block = False
            continue

        parts = line.split()
        if in_require_block:
            if len(parts) >= 2 and parts[0] == module_path:
                return parts[1]
            continue

        if len(parts) >= 3 and parts[0] == "require" and parts[1] == module_path:
            return parts[2]

    return None


def _normalize_go_version(version: str) -> str:
    """Return a Go module version with a leading v-prefix."""
    return version if version.startswith("v") else f"v{version}"


def _rust_version() -> str | None:
    """Read version from rust/Cargo.toml."""
    cargo = _REPO_ROOT / "rust" / "Cargo.toml"
    if not cargo.exists():
        return None
    text = cargo.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


_LANG_READERS = {
    "python": _python_version,
    "typescript/package": _typescript_package_version,
    "typescript/runtime": _typescript_runtime_version,
    "typescript/lockfile": _typescript_lockfile_version,
    "go": _go_version,
    "go/otel": _go_otel_version,
    "rust": _rust_version,
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

    ts_package = _typescript_package_version()
    ts_runtime = _typescript_runtime_version()
    ts_lockfile = _typescript_lockfile_version()
    if ts_package and ts_runtime and ts_package != ts_runtime:
        print(f"  typescript exact sync: runtime {ts_runtime} != package {ts_package}")
        errors.append(
            f"typescript runtime export version {ts_runtime} does not exactly match package.json {ts_package}"
        )
    if ts_package and ts_lockfile and ts_package != ts_lockfile:
        print(f"  typescript exact sync: lockfile {ts_lockfile} != package {ts_package}")
        errors.append(f"typescript package-lock version {ts_lockfile} does not exactly match package.json {ts_package}")

    go_version = _go_version()
    go_otel = _go_otel_version()
    if go_version and go_otel and go_version != go_otel:
        print(f"  go exact sync: go/otel {go_otel} != go {go_version}")
        errors.append(f"go/otel VERSION {go_otel} does not exactly match go VERSION {go_version}")

    otel_requires_go = _go_required_version(
        _REPO_ROOT / "go" / "otel" / "go.mod",
        "github.com/provide-io/provide-telemetry/go",
    )
    if go_version and otel_requires_go and otel_requires_go != _normalize_go_version(go_version):
        print(f"  go/otel dependency: core {otel_requires_go} != go VERSION {_normalize_go_version(go_version)}")
        errors.append(
            "go/otel go.mod dependency "
            f"{otel_requires_go} does not exactly match go VERSION {_normalize_go_version(go_version)}"
        )

    if errors:
        print(f"\nFAILED — {len(errors)} version mismatches.")
        return 1

    print("\nPASSED — all present languages match VERSION.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
