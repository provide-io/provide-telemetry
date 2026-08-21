#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Audit transitive NuGet dependencies for every project in the solution."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ci.audit_report import (
    Finding,
    assert_non_empty_inventory,
    fail_on_findings,
)

_REPO_ROOT = Path(os.environ.get("PROVIDE_REPO_ROOT", Path(__file__).resolve().parent.parent))
_CSHARP_DIR = _REPO_ROOT / "csharp"
# Floor, not a target. The solution enumerates 14 projects today; 5 is low
# enough to survive a project being retired and high enough that an unrestored
# or half-loaded solution cannot pass as a clean scan.
_MIN_PROJECTS = 5

# Resolved once so the subprocess calls carry an absolute path.
_DOTNET = shutil.which("dotnet") or "dotnet"


def _run(*args: str) -> str:
    if not _CSHARP_DIR.is_dir():
        print(f"csharp: no csharp/ directory under {_REPO_ROOT}", file=sys.stderr)
        raise SystemExit(2)
    result = subprocess.run(  # noqa: S603  # nosec B603 — fixed argv, no shell
        [_DOTNET, *args],
        cwd=_CSHARP_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and not result.stdout.strip():
        print(f"csharp: dotnet {' '.join(args)} failed\n{result.stderr}", file=sys.stderr)
        raise SystemExit(2)
    return result.stdout


def _findings_for(project: dict[str, object]) -> list[Finding]:
    findings: list[Finding] = []
    frameworks = project.get("frameworks") or []
    if not isinstance(frameworks, list):
        return findings
    for framework in frameworks:
        for key in ("topLevelPackages", "transitivePackages"):
            packages = framework.get(key) or []
            for package in packages:
                for vuln in package.get("vulnerabilities") or []:
                    findings.append(
                        Finding(
                            package=package.get("id", "?"),
                            installed=package.get("resolvedVersion", "?"),
                            advisory=vuln.get("advisoryurl", "?"),
                            severity=vuln.get("severity", "unknown"),
                            fixed_in="see advisory",
                        )
                    )
    return findings


def _audit() -> tuple[int, list[Finding]]:
    # Restore first: `list package` reports nothing on an unrestored solution,
    # which would otherwise look exactly like a clean result.
    _run("restore")
    raw = _run("list", "package", "--vulnerable", "--include-transitive", "--format", "json")
    if not raw.strip():
        print("csharp: dotnet list package produced no output", file=sys.stderr)
        raise SystemExit(2)
    report = json.loads(raw)
    projects = report.get("projects", [])
    findings = [finding for project in projects for finding in _findings_for(project)]
    return len(projects), findings


def main() -> int:
    project_count, findings = _audit()
    assert_non_empty_inventory(project_count, ecosystem="csharp", minimum=_MIN_PROJECTS)
    print(f"csharp: audited {project_count} projects")
    return fail_on_findings(findings, ecosystem="csharp")


if __name__ == "__main__":
    raise SystemExit(main())
