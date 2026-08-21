#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Audit the dependencies exported from the committed uv.lock.

Audits the lockfile rather than the repository as an installation path: the
committed lock is the deterministic artifact, and pointing pip-audit at the
directory makes it resolve and install, which is neither reproducible nor fast.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ci.audit_report import (
    Finding,
    assert_non_empty_inventory,
    fail_on_findings,
)

_REPO_ROOT = Path(os.environ.get("PROVIDE_REPO_ROOT", Path(__file__).resolve().parent.parent))
# Floor, not a target. The real graph is far larger; this only has to be high
# enough that an empty or truncated export cannot pass as clean.
_MIN_PACKAGES = 20

# Resolved once so the subprocess calls carry an absolute path.
_UV = shutil.which("uv") or "uv"


def _export_requirements() -> str:
    """Render the committed lock as a requirements file, dev groups included."""
    result = subprocess.run(  # noqa: S603  # nosec B603 — fixed argv, no shell
        [
            _UV,
            "export",
            "--frozen",
            "--all-groups",
            "--all-extras",
            "--no-hashes",
            "--no-emit-project",
            "--format",
            "requirements-txt",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _audit(requirements: str) -> tuple[int, list[Finding]]:
    with tempfile.TemporaryDirectory() as tmp:
        requirements_path = Path(tmp) / "requirements.txt"
        requirements_path.write_text(requirements, encoding="utf-8")
        result = subprocess.run(  # noqa: S603  # nosec B603 — fixed argv, no shell
            [
                _UV,
                "run",
                "pip-audit",
                "--requirement",
                str(requirements_path),
                # uv export already emits a fully-resolved pinned set, so
                # there is nothing to resolve. Without both of these, pip-audit
                # builds an isolated venv to resolve the file, which is slow
                # and — under a uv-managed interpreter — aborts in ensurepip.
                "--no-deps",
                "--disable-pip",
                # Fail rather than silently drop a package whose metadata could
                # not be collected; a partial inventory reads as clean.
                "--strict",
                "--format",
                "json",
                "--progress-spinner",
                "off",
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    if not result.stdout.strip():
        print(f"python: pip-audit produced no output\n{result.stderr}", file=sys.stderr)
        raise SystemExit(2)
    report = json.loads(result.stdout)
    dependencies = report.get("dependencies", [])
    findings = [
        Finding(
            package=dep.get("name", "?"),
            installed=dep.get("version", "?"),
            advisory=vuln.get("id", "?"),
            severity=vuln.get("severity") or "unknown",
            fixed_in=", ".join(vuln.get("fix_versions", [])) or "no fix published",
        )
        for dep in dependencies
        for vuln in dep.get("vulns", [])
    ]
    return len(dependencies), findings


def main() -> int:
    count, findings = _audit(_export_requirements())
    assert_non_empty_inventory(count, ecosystem="python", minimum=_MIN_PACKAGES)
    print(f"python: audited {count} packages from uv.lock")
    return fail_on_findings(findings, ecosystem="python")


if __name__ == "__main__":
    raise SystemExit(main())
