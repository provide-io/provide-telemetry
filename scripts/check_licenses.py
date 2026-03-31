# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Check that installed runtime and optional dependencies use permissive licenses.

Dev-only tools that carry copyleft licenses (e.g. codespell, reuse) are
explicitly excluded because they are never distributed with the package.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_LICENSES: frozenset[str] = frozenset(
    {
        "MIT",
        "MIT License",
        "MIT OR Apache-2.0",
        "Apache-2.0",
        "Apache Software License",
        "Apache-2.0 OR BSD-2-Clause",
        "BSD",
        "BSD License",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "3-Clause BSD License",
        "ISC",
        "ISC License",
        "PSF-2.0",
        "Python Software Foundation License",
        "MPL-2.0",
        "Mozilla Public License 2.0 (MPL 2.0)",
        "CC0 1.0 Universal (CC0 1.0) Public Domain Dedication",
        "Public Domain",
    }
)

ALLOWED_LICENSE_TOKENS: frozenset[str] = frozenset(
    {
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "MIT",
        "ISC",
        "PSF-2.0",
        "MPL-2.0",
    }
)

# Dev-only tools that are never distributed — copyleft is acceptable here.
DEV_ONLY_SKIP: frozenset[str] = frozenset(
    {
        "codespell",  # GPL-2.0-only
        "python-debian",  # GPLv2+   (transitive dep of reuse)
        "reuse",  # GPLv3+ (SPDX compliance tool)
        "docutils",  # Mixed: BSD/GPL/Public Domain (GPL clause applies only to
        # the command-line interface, not the library; kept as dev dep)
    }
)


def _get_installed_licenses() -> list[dict[str, str]]:
    pip_licenses = Path(sys.executable).parent / "pip-licenses"
    result = subprocess.run(
        [str(pip_licenses), "--format=json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def _license_allowed(license_str: str) -> bool:
    normalized = " ".join(license_str.strip().split())
    if normalized in ALLOWED_LICENSES or normalized in ALLOWED_LICENSE_TOKENS:
        return True

    if " OR " not in normalized and " AND " not in normalized:
        return False

    tokens = [tok.strip() for tok in re.split(r"\s+(?:OR|AND)\s+", normalized) if tok.strip()]
    if not tokens:
        return False
    return all(token in ALLOWED_LICENSE_TOKENS for token in tokens)


def main() -> int:
    packages = _get_installed_licenses()
    violations: list[str] = []
    skipped: list[str] = []

    for pkg in packages:
        name = pkg["Name"]
        license_str = pkg["License"]
        if name in DEV_ONLY_SKIP:
            skipped.append(name)
            continue
        if not _license_allowed(license_str):
            violations.append(f"  {name} {pkg['Version']}: {license_str!r}")

    if violations:
        print("Disallowed licenses found:")
        for v in violations:
            print(v)
        print("\nIf this is a dev-only tool, add it to DEV_ONLY_SKIP in scripts/check_licenses.py.")
        return 1

    checked = len(packages) - len(skipped)
    print(f"License check passed: {checked} packages checked, {len(skipped)} dev-only skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
