# Security and Coverage Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add blocking dependency-vulnerability gates for Python, TypeScript, Rust, and C#; upgrade the vulnerable Rust `h2` dependency; and make the Rust line-coverage gate provably enforce 100 percent.

**Architecture:** Every gate is a thin `ci/` script wrapping the ecosystem-native scanner, invoked from a workflow step. Each script does three things the raw scanner does not: it parses machine-readable output, it fails when the inventory is empty (a scanner that saw nothing is broken, not clean), and it exits non-zero on any unapproved finding. Rust alone gets an exception mechanism, in `rust/deny.toml`, with mandatory expiry dates policed by a checker. The coverage work is evidence-first: prove the current flag is inert before replacing it.

**Tech Stack:** `cargo-audit` + `cargo-deny` (Rust), `pip-audit` over `uv export` (Python), `npm audit --json` (TypeScript), `dotnet list package --vulnerable` (C#), `cargo-llvm-cov` (coverage). Scripts are Python 3.11+ or POSIX shell, per the existing `ci/` mix.

**Spec:** [`docs/superpowers/specs/2026-08-20-external-review-remediation-design.md`](../specs/2026-08-20-external-review-remediation-design.md) (revision 2) — workstream B.

## Global Constraints

- **Never put inline scripts in workflow YAML.** A `run:` block over 3 lines must be extracted to `ci/`. Obey any "script policy" comment in the workflow file.
- Add a short comment above every workflow step explaining what it does.
- **777 LOC max per file**; **SPDX headers required**; **mypy strict** for Python; **100% branch coverage** and **100% mutation kill** for anything under `src/`.
- New `ci/` scripts are tooling, not library code — put their tests under `tests/tooling/` and mark them `@pytest.mark.tooling`.
- **A scan that inventories zero packages is a failure, not a clean result.** Every gate must assert a non-zero inventory.
- **Each gate lands already blocking.** No "warn only" phase — a gate that cannot fail is the exact defect recommendation 6 exists to remove.
- Rust is the only ecosystem with an exception mechanism. Python, TypeScript, and C# findings are fixed by upgrading.
- No hardcoded machine paths. Derive paths from the script location with an env override.

## File Structure

- Create: `ci/audit_python.py` — export `uv.lock`, run `pip-audit`, assert inventory, fail on findings.
- Create: `ci/audit_typescript.sh` — `npm audit --json` over the full graph, piped to the shared parser.
- Create: `ci/audit_csharp.py` — `dotnet list package --vulnerable --include-transitive` across the solution.
- Create: `ci/audit_report.py` — shared parsing/assertion helpers used by the Python and C# scripts.
- Create: `rust/deny.toml` — `[advisories]` config; exceptions live here with mandatory `expires`.
- Create: `scripts/check_advisory_expiry.py` — fails on an expired or unexplained exception.
- Create: `tests/tooling/test_audit_report.py`, `tests/tooling/test_check_advisory_expiry.py`.
- Modify: `.github/workflows/ci-python.yml`, `ci-typescript.yml`, `ci-rust.yml`, `ci-csharp.yml` — one `dependency-audit` job each.
- Modify: `rust/Cargo.lock` — `h2` upgrade.
- Modify: `.github/workflows/ci-rust.yml:102` and `CLAUDE.md` — coverage flag, **only if Task 9 proves it necessary**.

---

### Task 1: Record the `h2` advisory as evidence

**Files:**
- Modify: `docs/superpowers/plans/2026-08-20-external-review-remediation-checklist.md` (advisory evidence block under recommendation 2)

**Interfaces:**
- Produces: the advisory ID, affected range, and patched version that Task 2 upgrades to. Nothing downstream may assume a version this task has not recorded.

The review did not record which advisory applies. `rust/Cargo.lock:514-516` pins
`h2 0.4.15`. Obtain the fact; do not assume it.

- [ ] **Step 1: Install the scanner**

Run: `cargo install cargo-audit --locked`
Expected: `cargo-audit` on `PATH`.

- [ ] **Step 2: Scan the committed lockfile**

Run: `cd rust && cargo audit --json > /tmp/claude-501/-Volumes-data-pyv-provide-telemetry/*/scratchpad/rust-audit-baseline.json; cargo audit`
Expected: human-readable output listing every advisory. Save both.

- [ ] **Step 3: Record what you found**

Fill the advisory evidence block in the umbrella checklist with the exact
advisory ID, affected version range, patched version, and the command you ran.

If `cargo audit` reports **no** advisory for `h2`, recommendation 2's `h2` half
is a false positive. Record that with the output, skip Task 2, and continue with
the gate tasks — the gates are the durable value regardless.

- [ ] **Step 4: Commit the evidence**

```bash
git add docs/superpowers/plans/2026-08-20-external-review-remediation-checklist.md
git commit -m "docs: record the cargo-audit baseline for the h2 advisory"
```

---

### Task 2: Upgrade `h2`

**Files:**
- Modify: `rust/Cargo.lock`

**Interfaces:**
- Consumes: the patched version recorded in Task 1.
- Produces: a lockfile that `cargo audit` passes.

- [ ] **Step 1: Try the constraint-respecting upgrade first**

Run: `cd rust && cargo update -p h2 && git diff --stat Cargo.lock`
Expected: `h2` moves to the patched version and **only** `h2` moves. A large diff
means the resolver pulled in more than asked — inspect it before continuing.

- [ ] **Step 2: Confirm the advisory is cleared**

Run: `cd rust && cargo audit`
Expected: no advisory for `h2`.

- [ ] **Step 3: If the patched version is unreachable, stop**

If `cargo update -p h2` cannot reach the patched version because a parent
constraint (`hyper`, `reqwest`, `opentelemetry-otlp`) pins it lower, that is a
scope expansion, not a lockfile bump. Record the blocking constraint in the
checklist, leave `Cargo.lock` untouched, and raise it. Do **not** widen the
change to bump the parent on your own initiative.

- [ ] **Step 4: Prove nothing broke**

Run: `cd rust && cargo build --all-features && cargo test --all-features`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add rust/Cargo.lock
git commit -m "fix(rust): upgrade h2 past the recorded advisory"
```

---

### Task 3: Shared audit-report helpers, with tests

**Files:**
- Create: `ci/audit_report.py`
- Create: `tests/tooling/test_audit_report.py`

**Interfaces:**
- Produces: `assert_non_empty_inventory(count: int, *, ecosystem: str, minimum: int) -> None` and `fail_on_findings(findings: list[Finding], *, ecosystem: str) -> int`, plus a `Finding` dataclass with `package`, `installed`, `advisory`, `severity`, `fixed_in`. Tasks 4 and 6 import both.

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""A scanner that inventories nothing is broken, not clean."""

from __future__ import annotations

import pytest

from ci.audit_report import Finding, assert_non_empty_inventory, fail_on_findings

pytestmark = pytest.mark.tooling


def test_zero_inventory_raises() -> None:
    with pytest.raises(SystemExit) as excinfo:
        assert_non_empty_inventory(0, ecosystem="python", minimum=10)
    assert excinfo.value.code != 0


def test_inventory_below_minimum_raises() -> None:
    with pytest.raises(SystemExit):
        assert_non_empty_inventory(9, ecosystem="python", minimum=10)


def test_inventory_at_minimum_is_accepted() -> None:
    assert_non_empty_inventory(10, ecosystem="python", minimum=10)


def test_no_findings_exits_zero() -> None:
    assert fail_on_findings([], ecosystem="python") == 0


def test_any_finding_exits_non_zero() -> None:
    finding = Finding(
        package="example",
        installed="1.0.0",
        advisory="GHSA-xxxx-xxxx-xxxx",
        severity="high",
        fixed_in="1.0.1",
    )
    assert fail_on_findings([finding], ecosystem="python") == 1


def test_finding_is_reported_with_its_advisory_and_fix(capsys: pytest.CaptureFixture[str]) -> None:
    finding = Finding(
        package="example",
        installed="1.0.0",
        advisory="GHSA-xxxx-xxxx-xxxx",
        severity="high",
        fixed_in="1.0.1",
    )
    fail_on_findings([finding], ecosystem="python")
    err = capsys.readouterr().err
    assert "GHSA-xxxx-xxxx-xxxx" in err
    assert "1.0.1" in err
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_audit_report.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'ci.audit_report'`. If `ci/`
is not importable, add an empty `ci/__init__.py` with an SPDX header in this step.

- [ ] **Step 3: Implement**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Shared assertions for the dependency-vulnerability gates.

Every ecosystem's scanner can succeed while having examined nothing — a lockfile
that failed to export, a solution that restored no projects, a registry that
returned an empty graph. That is indistinguishable from a clean scan in the exit
code, so the gates assert an inventory floor of their own.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    """One vulnerability report, normalised across ecosystems."""

    package: str
    installed: str
    advisory: str
    severity: str
    fixed_in: str


def assert_non_empty_inventory(count: int, *, ecosystem: str, minimum: int) -> None:
    """Exit non-zero when the scanner examined implausibly few packages."""
    if count < minimum:
        print(
            f"{ecosystem}: dependency audit inventoried {count} packages, "
            f"expected at least {minimum}. A scan that sees nothing is a broken "
            f"scan, not a clean one.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def fail_on_findings(findings: list[Finding], *, ecosystem: str) -> int:
    """Print every finding and return the process exit code."""
    if not findings:
        print(f"{ecosystem}: dependency audit clean")
        return 0
    print(f"{ecosystem}: {len(findings)} vulnerable package(s)", file=sys.stderr)
    for finding in findings:
        print(
            f"  - {finding.package} {finding.installed}: {finding.advisory} "
            f"({finding.severity}); fixed in {finding.fixed_in}",
            file=sys.stderr,
        )
    return 1
```

- [ ] **Step 4: Run the tests**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_audit_report.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ci/audit_report.py tests/tooling/test_audit_report.py
git commit -m "feat(ci): shared dependency-audit assertions

An empty inventory is a scanner failure, so the gates assert a floor rather
than trusting a zero-finding exit code."
```

---

### Task 4: Python gate — audit the committed `uv.lock`

**Files:**
- Create: `ci/audit_python.py`
- Modify: `.github/workflows/ci-python.yml`

**Interfaces:**
- Consumes: `ci.audit_report.Finding`, `assert_non_empty_inventory`, `fail_on_findings`.
- Produces: an executable script; exit 0 clean, 1 on findings, 2 on an empty inventory.

Audit the **lockfile**, not the repository as an installation path: the
committed lock is the deterministic artifact, and pointing `pip-audit` at the
directory makes it resolve and install, which is neither reproducible nor fast.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Audit the dependencies exported from the committed uv.lock."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ci.audit_report import Finding, assert_non_empty_inventory, fail_on_findings

_REPO_ROOT = Path(os.environ.get("PROVIDE_REPO_ROOT", Path(__file__).resolve().parent.parent))
# Floor, not a target. The real graph is far larger; this only has to be high
# enough that an empty or truncated export cannot pass as clean.
_MIN_PACKAGES = 20


def _export_requirements() -> str:
    """Render the committed lock as a requirements file, dev groups included."""
    result = subprocess.run(
        ["uv", "export", "--frozen", "--all-groups", "--all-extras", "--no-hashes", "--format", "requirements-txt"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _audit(requirements: str) -> tuple[int, list[Finding]]:
    result = subprocess.run(
        ["uv", "run", "pip-audit", "--requirement", "/dev/stdin", "--format", "json", "--progress-spinner", "off"],
        cwd=_REPO_ROOT,
        input=requirements,
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
            severity=vuln.get("severity", "unknown") or "unknown",
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
```

- [ ] **Step 2: Add `pip-audit` to the dev dependency group**

Run: `uv add --group dev pip-audit`
Expected: `pyproject.toml` and `uv.lock` updated.

- [ ] **Step 3: Run it locally**

Run: `uv run python ci/audit_python.py`
Expected: prints an audited-package count well above 20, then either "clean" or a
list of findings. **If it reports findings, fix them by upgrading before landing
the gate** — the gate lands blocking.

- [ ] **Step 4: Prove the empty-inventory guard fires**

Run: `uv run python -c "
from ci.audit_report import assert_non_empty_inventory
assert_non_empty_inventory(0, ecosystem='python', minimum=20)
"; echo \"exit=$?\"`
Expected: `exit=2` with the explanatory message.

- [ ] **Step 5: Prove a simulated finding fails the gate**

Temporarily append a line to the exported requirements inside `_export_requirements`
returning a known-vulnerable pin, run the script, observe exit 1 and the advisory
printed, then revert. Record the output in the checklist — this is the
falsifiability evidence, not an optional flourish.

- [ ] **Step 6: Wire it into CI**

Add to `.github/workflows/ci-python.yml` under `jobs:`:

```yaml
  # Fails the build on any known vulnerability in the committed uv.lock,
  # production and development dependencies alike. Blocking from day one.
  dependency-audit:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0  # v6
      - uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d  # v10.0.1
        with:
          python-version: "3.11"
      # Install the dev group so pip-audit itself is available.
      - name: Install dependencies
        run: uv sync --group dev
      # Export the committed lock and audit it; empty inventory = failure.
      - name: Audit Python dependencies
        run: uv run python ci/audit_python.py
```

Copy the action SHA pins from the existing jobs in that file rather than the ones
above if they have since moved — a stale pin is a silent downgrade.

- [ ] **Step 7: Commit**

```bash
git add ci/audit_python.py pyproject.toml uv.lock .github/workflows/ci-python.yml
git commit -m "ci(python): blocking dependency vulnerability gate"
```

---

### Task 5: TypeScript gate — upgrade findings first, then land it blocking

**Files:**
- Create: `ci/audit_typescript.sh`
- Modify: `typescript/package.json`, `typescript/package-lock.json`
- Modify: `.github/workflows/ci-typescript.yml`

**Interfaces:**
- Produces: an executable script; exit 0 clean, 1 on findings, 2 on an empty graph.

TypeScript is the one surface with known outstanding development findings, so its
ordering is fixed: **upgrade first, gate second, same plan**.

- [ ] **Step 1: See what is actually outstanding**

Run: `cd typescript && npm audit --json | head -100` and `npm audit`
Expected: a list of advisories. Record the count and the packages.

- [ ] **Step 2: Upgrade them away**

Run: `cd typescript && npm audit fix`
Then, for anything `npm audit fix` cannot resolve, upgrade the direct dependency
that pulls it in. Check `typescript/package.json` for the pin comment on
`vite ~8.0.16` — that pin exists because vite 8.1 breaks the vitest decorator
transform, so do **not** let `npm audit fix` float it. If a finding can only be
cleared by breaking that pin, stop and raise it.

- [ ] **Step 3: Confirm the suite still passes after the upgrades**

Run: `cd typescript && npm ci && npm test && npm run build`
Expected: PASS. A green audit with a broken build is not progress.

- [ ] **Step 4: Write the gate script**

```bash
#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
set -euo pipefail

# Audit the complete npm dependency graph — production and development.
# A graph with implausibly few packages means the audit examined nothing, which
# is a broken scan rather than a clean one, so we assert a floor.
readonly REPO_ROOT="${PROVIDE_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
readonly MIN_PACKAGES=100

cd "${REPO_ROOT}/typescript"

report="$(npm audit --json || true)"
if [[ -z "${report}" ]]; then
  echo "typescript: npm audit produced no output" >&2
  exit 2
fi

total="$(printf '%s' "${report}" | node -e '
  let raw = ""
  process.stdin.on("data", (d) => { raw += d })
  process.stdin.on("end", () => {
    const meta = JSON.parse(raw).metadata ?? {}
    const deps = meta.dependencies ?? {}
    const n = typeof deps === "number" ? deps : Object.values(deps).reduce((a, b) => a + b, 0)
    process.stdout.write(String(n))
  })
')"

if (( total < MIN_PACKAGES )); then
  echo "typescript: audit inventoried ${total} packages, expected at least ${MIN_PACKAGES}" >&2
  exit 2
fi
echo "typescript: audited ${total} packages"

# --audit-level=low so a low-severity advisory cannot slip through as clean.
npm audit --audit-level=low
```

- [ ] **Step 5: Run it**

Run: `chmod +x ci/audit_typescript.sh && ./ci/audit_typescript.sh`
Expected: prints the package count, then exits 0. Non-zero means Step 2 is not
finished — go back, do not weaken `--audit-level`.

- [ ] **Step 6: Prove the floor fires**

Run: `PROVIDE_REPO_ROOT=$(mktemp -d) ./ci/audit_typescript.sh; echo "exit=$?"`
Expected: exit 2 — no `typescript/` directory, so no inventory. Record it.

- [ ] **Step 7: Wire it into CI**

```yaml
  # Blocks on any npm advisory across the full production+dev graph. The floor
  # check makes an empty or failed audit fail rather than read as clean.
  dependency-audit:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0  # v6
      - uses: actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e  # v6
        with:
          node-version: '24'
      # Install from the lockfile so the audited graph is the committed one.
      - name: Install dependencies
        run: npm ci
        working-directory: typescript
      - name: Audit npm dependencies
        run: ./ci/audit_typescript.sh
```

- [ ] **Step 8: Commit**

```bash
git add typescript/package.json typescript/package-lock.json ci/audit_typescript.sh .github/workflows/ci-typescript.yml
git commit -m "ci(typescript): upgrade audit findings and gate the dependency graph"
```

---

### Task 6: C# gate — transitive NuGet across the whole solution

**Files:**
- Create: `ci/audit_csharp.py`
- Modify: `.github/workflows/ci-csharp.yml`

**Interfaces:**
- Consumes: `ci.audit_report.Finding`, `assert_non_empty_inventory`, `fail_on_findings`.
- Produces: an executable script; exit 0 clean, 1 on findings, 2 on an empty inventory.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Audit transitive NuGet dependencies for every project in the solution."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ci.audit_report import Finding, assert_non_empty_inventory, fail_on_findings

_REPO_ROOT = Path(os.environ.get("PROVIDE_REPO_ROOT", Path(__file__).resolve().parent.parent))
_CSHARP_DIR = _REPO_ROOT / "csharp"
# Floor: the solution has multiple projects, each with a non-trivial graph.
_MIN_PROJECTS = 2


def _run(*args: str) -> str:
    result = subprocess.run(args, cwd=_CSHARP_DIR, capture_output=True, text=True, check=False)
    if result.returncode != 0 and not result.stdout.strip():
        print(f"csharp: {' '.join(args)} failed\n{result.stderr}", file=sys.stderr)
        raise SystemExit(2)
    return result.stdout


def _audit() -> tuple[int, list[Finding]]:
    # Restore first: `list package` reports nothing on an unrestored solution,
    # which would otherwise look exactly like a clean result.
    _run("dotnet", "restore")
    raw = _run("dotnet", "list", "package", "--vulnerable", "--include-transitive", "--format", "json")
    if not raw.strip():
        print("csharp: dotnet list package produced no output", file=sys.stderr)
        raise SystemExit(2)
    report = json.loads(raw)
    projects = report.get("projects", [])
    findings: list[Finding] = []
    for project in projects:
        for framework in project.get("frameworks") or []:
            for key in ("topLevelPackages", "transitivePackages"):
                for package in framework.get(key) or []:
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
    return len(projects), findings


def main() -> int:
    project_count, findings = _audit()
    assert_non_empty_inventory(project_count, ecosystem="csharp", minimum=_MIN_PROJECTS)
    print(f"csharp: audited {project_count} projects")
    return fail_on_findings(findings, ecosystem="csharp")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it**

Run: `uv run python ci/audit_csharp.py`
Expected: an audited-project count of at least 2, then clean. Findings must be
upgraded away before the gate lands.

- [ ] **Step 3: Prove the inventory floor fires**

Run: `PROVIDE_REPO_ROOT=$(mktemp -d) uv run python ci/audit_csharp.py; echo "exit=$?"`
Expected: exit 2. Record it.

- [ ] **Step 4: Wire it into CI**

```yaml
  # Blocks on any vulnerable NuGet package, transitive included, in every
  # project of the solution. Restores first so an unrestored solution cannot
  # report an empty — and therefore falsely clean — package list.
  dependency-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0  # v6
      - uses: actions/setup-dotnet@26b0ec14cb23fa6904739307f278c14f94c95bf1  # v5.4.0
        with:
          dotnet-version: "10.0.x"
      - uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d  # v10.0.1
        with:
          python-version: "3.11"
      - name: Audit NuGet dependencies
        run: uv run python ci/audit_csharp.py
```

- [ ] **Step 5: Commit**

```bash
git add ci/audit_csharp.py .github/workflows/ci-csharp.yml
git commit -m "ci(csharp): blocking transitive NuGet vulnerability gate"
```

---

### Task 7: Rust gate — `cargo-audit` plus an exception mechanism that expires

**Files:**
- Create: `rust/deny.toml`
- Create: `scripts/check_advisory_expiry.py`
- Create: `tests/tooling/test_check_advisory_expiry.py`
- Modify: `.github/workflows/ci-rust.yml`

**Interfaces:**
- Produces: `check_advisory_expiry.validate(config: dict, today: datetime.date) -> list[str]` — the pure function the tests drive; `main()` reads `rust/deny.toml` and calls it.

Rust is the only ecosystem with an exception mechanism, because a RustSec
advisory can land on a transitive with no patched release for weeks. An
exception without an expiry is a permanent silent downgrade, so expiry is
mandatory and checked.

- [ ] **Step 1: Write the failing checker tests**

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""An advisory exception without a live expiry and a reason is not an exception."""

from __future__ import annotations

import datetime as dt

import pytest

from scripts.check_advisory_expiry import validate

pytestmark = pytest.mark.tooling

_TODAY = dt.date(2026, 8, 20)


def test_no_exceptions_is_clean() -> None:
    assert validate({"advisories": {"ignore": []}}, _TODAY) == []


def test_live_exception_with_reason_is_clean() -> None:
    config = {
        "advisories": {
            "ignore": [
                {"id": "RUSTSEC-2026-0001", "reason": "no patched release yet; upstream #42", "expires": "2026-10-01"}
            ]
        }
    }
    assert validate(config, _TODAY) == []


def test_expired_exception_is_an_error() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "reason": "stale", "expires": "2026-08-19"}]}}
    errors = validate(config, _TODAY)
    assert any("expired" in error for error in errors)


def test_exception_expiring_today_is_still_live() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "reason": "ok", "expires": "2026-08-20"}]}}
    assert validate(config, _TODAY) == []


def test_missing_expiry_is_an_error() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "reason": "ok"}]}}
    assert any("expires" in error for error in validate(config, _TODAY))


def test_missing_reason_is_an_error() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "expires": "2026-10-01"}]}}
    assert any("reason" in error for error in validate(config, _TODAY))


def test_expiry_further_out_than_ninety_days_is_an_error() -> None:
    config = {"advisories": {"ignore": [{"id": "RUSTSEC-2026-0001", "reason": "ok", "expires": "2027-01-01"}]}}
    assert any("90 days" in error for error in validate(config, _TODAY))
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_check_advisory_expiry.py`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the checker**

```python
#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Fail on a RustSec advisory exception that is expired, undated, or unexplained."""

from __future__ import annotations

import datetime as dt
import os
import sys
import tomllib
from pathlib import Path

_REPO_ROOT = Path(os.environ.get("PROVIDE_REPO_ROOT", Path(__file__).resolve().parent.parent))
_DENY_PATH = _REPO_ROOT / "rust" / "deny.toml"
_MAX_HORIZON_DAYS = 90


def validate(config: dict[str, object], today: dt.date) -> list[str]:
    """Return one error string per unacceptable exception entry."""
    advisories = config.get("advisories") or {}
    if not isinstance(advisories, dict):
        return ["deny.toml: [advisories] must be a table"]
    entries = advisories.get("ignore") or []
    if not isinstance(entries, list):
        return ["deny.toml: [advisories].ignore must be an array"]

    errors: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append(f"deny.toml: ignore entry must be a table, got {entry!r}")
            continue
        identifier = entry.get("id", "<no id>")
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{identifier}: missing reason — say why this is accepted")
        raw_expiry = entry.get("expires")
        if not isinstance(raw_expiry, str) or not raw_expiry:
            errors.append(f"{identifier}: missing expires — an exception without an expiry is permanent")
            continue
        try:
            expires = dt.date.fromisoformat(raw_expiry)
        except ValueError:
            errors.append(f"{identifier}: expires {raw_expiry!r} is not an ISO date")
            continue
        if expires < today:
            errors.append(f"{identifier}: expired on {expires.isoformat()} — re-review or remove it")
        elif (expires - today).days > _MAX_HORIZON_DAYS:
            errors.append(f"{identifier}: expires {expires.isoformat()}, more than 90 days out")
    return errors


def main() -> int:
    if not _DENY_PATH.is_file():
        print(f"{_DENY_PATH} not found", file=sys.stderr)
        return 1
    config = tomllib.loads(_DENY_PATH.read_text(encoding="utf-8"))
    errors = validate(config, dt.date.today())
    if errors:
        print("Advisory exception gate failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Advisory exception gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`dt.date.today()` appears only in `main()`, never in `validate()`, so the tests
stay deterministic.

- [ ] **Step 4: Run the tests**

Run: `uv run python scripts/run_pytest_gate.py --no-cov -q tests/tooling/test_check_advisory_expiry.py`
Expected: PASS.

- [ ] **Step 5: Create `rust/deny.toml` with no exceptions**

```toml
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.

# RustSec advisory policy. Every advisory blocks the build.
#
# To accept one temporarily, add an entry to [advisories].ignore with:
#   id      — the RUSTSEC identifier
#   reason  — why it is accepted; name the upstream issue or the blocking pin
#   expires — an ISO date, at most 90 days out
#
# scripts/check_advisory_expiry.py fails the build on an entry that is expired,
# undated, unexplained, or dated further than 90 days ahead, so an exception
# cannot outlive its review. The reviewer is whoever approves the pull request
# that adds it.
[advisories]
ignore = []
```

- [ ] **Step 6: Run both Rust gates**

Run: `cd rust && cargo audit && cd .. && uv run python scripts/check_advisory_expiry.py`
Expected: both PASS.

- [ ] **Step 7: Prove an expired exception fails**

Temporarily add an entry with `expires = "2020-01-01"`, run
`uv run python scripts/check_advisory_expiry.py`, observe exit 1 naming it as
expired, then remove the entry. Record the output.

- [ ] **Step 8: Wire it into CI**

```yaml
  # Blocks on any RustSec advisory against the committed Cargo.lock, and
  # separately rejects an advisory exception that is expired or unexplained.
  dependency-audit:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0  # v6
      - uses: dtolnay/rust-toolchain@29eef336d9b2848a0b548edc03f92a220660cdb8  # stable@2026-04-18
        with:
          toolchain: stable
      - uses: astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d  # v10.0.1
        with:
          python-version: "3.11"
      - name: Install cargo-audit
        run: cargo install cargo-audit --locked
      # Audit the committed lockfile — no resolution, no network drift.
      - name: Audit Rust dependencies
        run: cargo audit
        working-directory: rust
      # An exception without a live expiry and a reason is a silent downgrade.
      - name: Check advisory exception expiry
        run: uv run python scripts/check_advisory_expiry.py
```

- [ ] **Step 9: Commit**

```bash
git add rust/deny.toml scripts/check_advisory_expiry.py tests/tooling/test_check_advisory_expiry.py .github/workflows/ci-rust.yml
git commit -m "ci(rust): blocking cargo-audit gate with expiring exceptions"
```

---

### Task 8: Go — confirm the existing controls, add nothing

**Files:** none modified.

- [ ] **Step 1: Confirm `gosec` and `govulncheck` run and block**

Run: `grep -n "gosec\|govulncheck" .github/workflows/ci-go.yml`
Expected: both appear as steps with no `continue-on-error`.

- [ ] **Step 2: Record the finding in the checklist**

If either is missing or non-blocking, that is a new finding — record it in the
checklist under recommendation 2 and raise it. Do not silently add a gate the
design did not scope.

---

### Task 9: Rust coverage — prove the flag is inert before replacing it

**Files:**
- Modify (conditionally): `.github/workflows/ci-rust.yml:102`, `CLAUDE.md`

**Interfaces:**
- Consumes: `cargo-llvm-cov` 0.8.5, the exact command at `.github/workflows/ci-rust.yml:102`.
- Produces: either a documented false-positive closure, or a changed flag with fixture evidence.

The review calls `--fail-uncovered-lines 0` ineffective. That is a claim, not a
fact, and `--fail-uncovered-lines 0` and `--fail-under-lines 100` are close
enough in meaning that swapping them blind could be a no-op rename. Test it.

- [ ] **Step 1: Build a fixture crate with a known-uncovered line**

```bash
mkdir -p /tmp/claude-501/-Volumes-data-pyv-provide-telemetry/*/scratchpad/covfixture/src
cd /tmp/claude-501/-Volumes-data-pyv-provide-telemetry/*/scratchpad/covfixture
cat > Cargo.toml <<'TOML'
[package]
name = "covfixture"
version = "0.1.0"
edition = "2021"
TOML
cat > src/lib.rs <<'RS'
pub fn covered(a: i32) -> i32 { a + 1 }

// Never called by any test: one uncovered function, one uncovered line.
pub fn uncovered(a: i32) -> i32 { a - 1 }

#[cfg(test)]
mod tests {
    #[test]
    fn calls_covered_only() { assert_eq!(super::covered(1), 2); }
}
RS
```

- [ ] **Step 2: Run the CURRENT command against the fixture**

```bash
cargo llvm-cov --all-targets --all-features \
  --ignore-filename-regex '/rustlib/src/rust/library/|/\.rustup/|/toolchains/' \
  --fail-uncovered-lines 0 --fail-under-functions 100
echo "exit=$?"
```

Record the exit code. Two outcomes, two different plans:

- [ ] **Step 3a: If it exits NON-ZERO — the flag works**

Recommendation 3 is a false positive. Record the fixture, the command, and the
exit code in the checklist, tick recommendation 3 as closed-with-evidence, change
nothing in `ci-rust.yml` or `CLAUDE.md`, and skip to Task 10. Note explicitly in
the checklist that the flag was verified rather than replaced.

- [ ] **Step 3b: If it exits ZERO — the flag is inert**

Re-run with the replacement and confirm the fixture now fails:

```bash
cargo llvm-cov --all-targets --all-features \
  --ignore-filename-regex '/rustlib/src/rust/library/|/\.rustup/|/toolchains/' \
  --fail-under-lines 100 --fail-under-functions 100
echo "exit=$?"
```
Expected: non-zero. If it *also* exits zero, neither flag enforces line coverage
in this version — record that and raise it rather than shipping a second inert flag.

- [ ] **Step 4 (only if 3b): Change the workflow**

In `.github/workflows/ci-rust.yml:102`, replace `--fail-uncovered-lines 0` with
`--fail-under-lines 100`. Keep `--fail-under-functions 100`.

- [ ] **Step 5 (only if 3b): Change `CLAUDE.md` in lockstep**

`CLAUDE.md` documents the same command verbatim under "Quality Constraints". Update
it identically. A drift here fails `scripts/check_docs_accuracy.py` and, worse,
tells the next contributor to run a command CI does not run.

- [ ] **Step 6: Run the real coverage gate**

```bash
cd rust && cargo llvm-cov --all-targets --all-features \
  --ignore-filename-regex '/rustlib/src/rust/library/|/\.rustup/|/toolchains/' \
  --fail-under-lines 100 --fail-under-functions 100
```
Expected: PASS. A failure means the repository has genuinely uncovered lines that
the inert flag was hiding — that is a real finding. Record it and fix the coverage
rather than relaxing the threshold.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci-rust.yml CLAUDE.md
git commit -m "ci(rust): enforce 100% line coverage with a flag that fires

The fixture in the checklist shows the previous argument passing on a report
with an uncovered line."
```

---

### Task 10: Full verification and checklist update

- [ ] **Step 1: Run every gate this plan touched**

```bash
uv run python ci/audit_python.py
./ci/audit_typescript.sh
uv run python ci/audit_csharp.py
cd rust && cargo audit && cd ..
uv run python scripts/check_advisory_expiry.py
```
Expected: all pass with non-zero inventories printed.

- [ ] **Step 2: Run the repository gates**

```bash
uv run python scripts/run_pytest_gate.py
uv run ruff format --check . && uv run ruff check . && uv run mypy src tests
uv run bandit -r src -ll && uv run codespell
uv run python scripts/check_max_loc.py --max-lines 777
uv run python scripts/check_spdx_headers.py
cd rust && cargo test --all-features
git status --short
```
Expected: all pass; clean tree.

- [ ] **Step 3: Run the Python mutation gate**

Run: `uv run python scripts/run_mutation_gate.py --max-children 2 --min-mutation-score 95`
Expected: zero survivors. `ci/` scripts are tooling; if the gate's scope includes
them and a survivor appears in the new parsing code, add the missing case to
`tests/tooling/`.

- [ ] **Step 4: Update the umbrella checklist**

Tick recommendations 2 and 3 in
`docs/superpowers/plans/2026-08-20-external-review-remediation-checklist.md` and
paste real command output into their evidence blocks — including the advisory ID
from Task 1 and the coverage-fixture exit codes from Task 9. Leave anything
unproven unticked.
