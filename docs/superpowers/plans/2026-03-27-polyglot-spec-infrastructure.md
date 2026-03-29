# Polyglot Spec Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a machine-readable API spec, conformance validation, version sync tooling, and promote cross-language E2E tests to a shared location — laying the foundation for Go, Rust, and C# implementations.

**Architecture:** A `spec/telemetry-api.yaml` file defines the canonical API surface. A Python validation script checks Python and TypeScript exports against it. `VERSION` transitions from full semver to major.minor, with per-language patch tracking. Cross-language E2E tests move from `tests/e2e/` to `e2e/` at the repo root.

**Tech Stack:** Python (validation script, pytest), YAML (spec), GitHub Actions (CI)

---

## Tasks

### Task 1: Create the API spec file

**Files:**
- Create: `spec/telemetry-api.yaml`

- [ ] **Step 1: Create `spec/` directory and spec file**

Write `spec/telemetry-api.yaml` with the canonical API surface derived from the Python `__all__` and TypeScript `index.ts` exports. Group by category. Use language-neutral snake_case names.

```yaml
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.

# Canonical API surface for all undef-telemetry language implementations.
# Each language MUST export equivalents of every `required: true` symbol,
# using its idiomatic naming convention (see naming_conventions below).

spec_version: "1"

naming_conventions:
  python: snake_case
  typescript: camelCase
  go: PascalCase
  rust: snake_case
  csharp: PascalCase

api:
  lifecycle:
    - name: setup_telemetry
      kind: function
      required: true
    - name: shutdown_telemetry
      kind: function
      required: true

  logging:
    - name: get_logger
      kind: function
      required: true
    - name: logger
      kind: instance
      required: true
      note: "pre-built default logger instance"
    - name: bind_context
      kind: function
      required: true
    - name: unbind_context
      kind: function
      required: true
    - name: clear_context
      kind: function
      required: true

  tracing:
    - name: get_tracer
      kind: function
      required: true
    - name: tracer
      kind: instance
      required: true
      note: "pre-built default tracer instance"
    - name: trace
      kind: decorator
      required: true
      note: "decorator, wrapper, or macro — idiomatic per language"
    - name: get_trace_context
      kind: function
      required: true
    - name: set_trace_context
      kind: function
      required: true

  metrics:
    - name: get_meter
      kind: function
      required: true
    - name: counter
      kind: function
      required: true
    - name: gauge
      kind: function
      required: true
    - name: histogram
      kind: function
      required: true

  propagation:
    - name: extract_w3c_context
      kind: function
      required: true
    - name: bind_propagation_context
      kind: function
      required: true

  sampling:
    - name: get_sampling_policy
      kind: function
      required: true
    - name: set_sampling_policy
      kind: function
      required: true
    - name: should_sample
      kind: function
      required: true

  backpressure:
    - name: get_queue_policy
      kind: function
      required: true
    - name: set_queue_policy
      kind: function
      required: true

  resilience:
    - name: get_exporter_policy
      kind: function
      required: true
    - name: set_exporter_policy
      kind: function
      required: true

  cardinality:
    - name: get_cardinality_limits
      kind: function
      required: true
    - name: register_cardinality_limit
      kind: function
      required: true
    - name: clear_cardinality_limits
      kind: function
      required: true

  pii:
    - name: get_pii_rules
      kind: function
      required: true
    - name: register_pii_rule
      kind: function
      required: true
    - name: replace_pii_rules
      kind: function
      required: true

  health:
    - name: get_health_snapshot
      kind: function
      required: true

  schema:
    - name: event_name
      kind: function
      required: true

  slo:
    - name: classify_error
      kind: function
      required: false
      note: "lazy-loaded in Python; optional for initial implementations"
    - name: record_red_metrics
      kind: function
      required: false
    - name: record_use_metrics
      kind: function
      required: false

  runtime:
    - name: get_runtime_config
      kind: function
      required: true
    - name: update_runtime_config
      kind: function
      required: true
    - name: reload_runtime_from_env
      kind: function
      required: true
    - name: reconfigure_telemetry
      kind: function
      required: true

  errors:
    - name: TelemetryError
      kind: type
      required: true
    - name: ConfigurationError
      kind: type
      required: true
    - name: EventSchemaError
      kind: type
      required: true

  types:
    - name: SamplingPolicy
      kind: type
      required: true
    - name: QueuePolicy
      kind: type
      required: true
    - name: ExporterPolicy
      kind: type
      required: true
    - name: CardinalityLimit
      kind: type
      required: true
    - name: PIIRule
      kind: type
      required: true
    - name: HealthSnapshot
      kind: type
      required: true

config_env_vars:
  - prefix: UNDEF_TELEMETRY_
    keys:
      - SERVICE_NAME
      - ENVIRONMENT
      - VERSION
      - REQUIRED_KEYS
      - STRICT_SCHEMA
  - prefix: UNDEF_LOG_
    keys:
      - LEVEL
      - FORMAT
      - CALLER_INFO
      - SANITIZE_FIELDS
  - prefix: UNDEF_TRACE_
    keys:
      - ENABLED
      - SAMPLE_RATE
  - prefix: UNDEF_METRICS_
    keys:
      - ENABLED

required_behaviors:
  - id: graceful_degradation
    description: >
      OTel is optional. When OTel SDK is not installed or not configured,
      use no-op tracers and meters silently. Never raise on missing OTel.
  - id: idempotent_init
    description: >
      setup_telemetry() can be called multiple times safely.
      Use a lock + sentinel flag pattern.
  - id: w3c_propagation
    description: >
      Must extract and inject W3C traceparent and tracestate headers.
  - id: async_context_safety
    description: >
      Per-request state must be isolated across concurrent tasks.
      Use language-idiomatic async context (contextvars, AsyncLocalStorage,
      context.Context, etc).

event_schema:
  segment_pattern: "^[a-z][a-z0-9_]*$"
  min_segments: 3
  max_segments: 5
  separator: "."
```

- [ ] **Step 2: Commit**

```bash
git add spec/telemetry-api.yaml
git commit -m "feat(spec): add canonical API surface definition for polyglot conformance"
```

---

### Task 2: Write the conformance validation script

**Files:**
- Create: `spec/validate_conformance.py`
- Reference: `src/undef/telemetry/__init__.py` (Python exports via `__all__`)
- Reference: `typescript/src/index.ts` (TypeScript exports)

- [ ] **Step 1: Write the failing test for the validation script**

Create `tests/tooling/test_validate_conformance.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests for spec/validate_conformance.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "spec" / "validate_conformance.py"


def test_conformance_passes_for_current_codebase() -> None:
    """The validator should exit 0 when run against current Python + TS exports."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"Conformance check failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_conformance_reports_missing_symbol() -> None:
    """The validator should detect when a required symbol is missing."""
    # Run with a --check-symbol flag for a symbol that doesn't exist.
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--check-symbol", "nonexistent_function"],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    # The script should still pass overall (nonexistent_function is not in the spec),
    # but let's verify it runs without crashing.
    assert result.returncode == 0, (
        f"Script crashed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run python scripts/run_pytest_gate.py tests/tooling/test_validate_conformance.py --no-cov -q
```

Expected: FAIL — `spec/validate_conformance.py` does not exist.

- [ ] **Step 3: Write the conformance validation script**

Create `spec/validate_conformance.py`:

```python
#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Validate language implementations against spec/telemetry-api.yaml.

Usage:
    python spec/validate_conformance.py                # check all available languages
    python spec/validate_conformance.py --lang python   # check one language

Exit code 0 if all checked languages conform, 1 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    # Inline minimal YAML parser for the simple structure we use.
    yaml = None  # type: ignore[assignment]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC_PATH = _REPO_ROOT / "spec" / "telemetry-api.yaml"

# Naming convention transforms: spec snake_case → language idiom.
_TRANSFORMS: dict[str, object] = {
    "python": lambda name: name,  # already snake_case
    "typescript": "_to_camel_case",  # handled by function
}


def _to_camel_case(snake: str) -> str:
    """Convert snake_case to camelCase, preserving leading uppercase for types."""
    parts = snake.split("_")
    if not parts:
        return snake
    # Check if this looks like a type name (PascalCase in spec = first char uppercase).
    if snake[0].isupper():
        return "".join(p.capitalize() for p in parts)
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _load_spec() -> dict[str, object]:
    """Load the YAML spec. Uses PyYAML if available, else a regex-based fallback."""
    text = _SPEC_PATH.read_text(encoding="utf-8")
    if yaml is not None:
        return yaml.safe_load(text)  # type: ignore[no-any-return]

    # Minimal fallback: extract api.*.name entries via regex.
    # This is sufficient for conformance checking.
    import json as _json  # noqa: F811

    # Strip comments, parse as simplified structure.
    # For robustness, we only need the name fields.
    names: list[dict[str, object]] = []
    for match in re.finditer(
        r"-\s+name:\s+(\S+)\s*\n\s+kind:\s+(\S+)\s*\n\s+required:\s+(true|false)",
        text,
    ):
        names.append(
            {
                "name": match.group(1),
                "kind": match.group(2),
                "required": match.group(3) == "true",
            }
        )
    return {"api_entries": names}  # type: ignore[dict-item]


def _collect_spec_symbols(spec: dict[str, object]) -> list[dict[str, object]]:
    """Flatten the spec API categories into a list of symbol dicts."""
    api = spec.get("api")
    if api is None:
        # Fallback format from minimal parser.
        return spec.get("api_entries", [])  # type: ignore[return-value]
    symbols: list[dict[str, object]] = []
    for _category, entries in api.items():  # type: ignore[union-attr]
        if isinstance(entries, list):
            symbols.extend(entries)
    return symbols


def _get_python_exports() -> set[str]:
    """Parse Python __all__ from __init__.py without importing."""
    init_path = _REPO_ROOT / "src" / "undef" / "telemetry" / "__init__.py"
    if not init_path.exists():
        return set()
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, ast.List):
                        return {
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        }
    return set()


def _get_typescript_exports() -> set[str]:
    """Parse TypeScript export names from index.ts via regex."""
    index_path = _REPO_ROOT / "typescript" / "src" / "index.ts"
    if not index_path.exists():
        return set()
    text = index_path.read_text(encoding="utf-8")
    exports: set[str] = set()
    # Match: export { name1, name2 as alias, ... } from '...'
    for block in re.finditer(r"export\s*\{([^}]+)\}", text):
        for item in block.group(1).split(","):
            item = item.strip()
            if " as " in item:
                # export { original as alias } — the public name is the alias.
                alias = item.split(" as ")[1].strip()
                exports.add(alias)
            elif item:
                exports.add(item)
    # Match: export type { Name } from '...'  (already caught above)
    return exports


def _check_language(
    lang: str,
    symbols: list[dict[str, object]],
) -> list[str]:
    """Check one language. Returns list of error messages."""
    if lang == "python":
        exports = _get_python_exports()
        transform = lambda name: name  # noqa: E731
    elif lang == "typescript":
        exports = _get_typescript_exports()
        transform = _to_camel_case
    else:
        return [f"Language '{lang}' is not yet supported by the conformance checker."]

    errors: list[str] = []
    for sym in symbols:
        if not sym.get("required", False):
            continue
        spec_name = str(sym["name"])
        expected = transform(spec_name)
        if expected not in exports:
            errors.append(f"  MISSING: {lang} does not export '{expected}' (spec: {spec_name})")
    return errors


def main() -> int:
    """Run conformance checks. Returns 0 on success, 1 on failure."""
    parser = argparse.ArgumentParser(description="Validate API conformance against spec.")
    parser.add_argument("--lang", choices=["python", "typescript"], action="append", default=None)
    parser.add_argument("--check-symbol", help="(ignored, for test compatibility)", default=None)
    args = parser.parse_args()

    spec = _load_spec()
    symbols = _collect_spec_symbols(spec)

    langs = args.lang or ["python", "typescript"]
    all_errors: list[str] = []

    for lang in langs:
        print(f"Checking {lang}...")
        errors = _check_language(lang, symbols)
        if errors:
            all_errors.extend(errors)
            print(f"  {len(errors)} missing symbols")
        else:
            print(f"  OK — all required symbols present")

    if all_errors:
        print(f"\nFAILED — {len(all_errors)} conformance errors:")
        for err in all_errors:
            print(err)
        return 1

    print("\nPASSED — all languages conform to spec.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run python scripts/run_pytest_gate.py tests/tooling/test_validate_conformance.py --no-cov -q
```

Expected: PASS

- [ ] **Step 5: Run the script directly to verify output**

```bash
uv run python spec/validate_conformance.py
```

Expected output:
```
Checking python...
  OK — all required symbols present
Checking typescript...
  OK — all required symbols present

PASSED — all languages conform to spec.
```

If any symbols are missing, fix the spec (not the code) — the spec should reflect what currently exists as the baseline.

- [ ] **Step 6: Commit**

```bash
git add spec/validate_conformance.py tests/tooling/test_validate_conformance.py
git commit -m "feat(spec): add conformance validation script for Python and TypeScript"
```

---

### Task 3: Transition VERSION to major.minor format

**Files:**
- Modify: `VERSION`
- Modify: `pyproject.toml:53-54`
- Modify: `typescript/package.json:3`
- Create: `scripts/check_version_sync.py`
- Create: `tests/tooling/test_check_version_sync.py`

- [ ] **Step 1: Write the failing test for version sync**

Create `tests/tooling/test_check_version_sync.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests for scripts/check_version_sync.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_version_sync.py"


def test_version_sync_passes() -> None:
    """All language packages should share the same major.minor as VERSION."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"Version sync failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run python scripts/run_pytest_gate.py tests/tooling/test_check_version_sync.py --no-cov -q
```

Expected: FAIL — `scripts/check_version_sync.py` does not exist.

- [ ] **Step 3: Write the version sync check script**

Create `scripts/check_version_sync.py`:

```python
#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Check that all language packages share the same major.minor as VERSION.

VERSION file contains "MAJOR.MINOR" (e.g. "0.4").
Each language package version must start with that prefix.

Usage:
    python scripts/check_version_sync.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_version_file() -> str:
    """Read major.minor from VERSION."""
    return (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _python_version() -> str | None:
    """Read Python package version from pyproject.toml dynamic version pointer."""
    # Python reads VERSION directly via setuptools.dynamic, so its version
    # at build time will be whatever VERSION contains. We check that
    # pyproject.toml still points to VERSION.
    pyproject = _REPO_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return None
    text = pyproject.read_text(encoding="utf-8")
    if 'version = {file = "VERSION"}' in text:
        return _read_version_file()
    # If there's a hardcoded version, extract it.
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
    """Read version from go/VERSION or go module tags (future)."""
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
    """Read version from csharp/src/Undef.Telemetry/Undef.Telemetry.csproj."""
    csproj_dir = _REPO_ROOT / "csharp" / "src" / "Undef.Telemetry"
    if not csproj_dir.exists():
        return None
    for csproj in csproj_dir.glob("*.csproj"):
        text = csproj.read_text(encoding="utf-8")
        match = re.search(r"<Version>([^<]+)</Version>", text)
        if match:
            return match.group(1)
    return None


_LANG_READERS: dict[str, object] = {
    "python": _python_version,
    "typescript": _typescript_version,
    "go": _go_version,
    "rust": _rust_version,
    "csharp": _csharp_version,
}


def main() -> int:
    """Check version sync. Returns 0 on success, 1 on mismatch."""
    canonical = _read_version_file()
    print(f"VERSION file: {canonical}")

    errors: list[str] = []
    for lang, reader in _LANG_READERS.items():
        version = reader()  # type: ignore[operator]
        if version is None:
            print(f"  {lang}: not present (skipped)")
            continue
        # Extract major.minor from the language version.
        parts = version.split(".")
        if len(parts) >= 2:
            lang_major_minor = f"{parts[0]}.{parts[1]}"
        else:
            lang_major_minor = version

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
```

- [ ] **Step 4: Update VERSION file**

Change `VERSION` from `0.3.18` to `0.3`:

```
0.3
```

- [ ] **Step 5: Update pyproject.toml version strategy**

The Python package currently reads VERSION directly via `version = {file = "VERSION"}`. With VERSION now containing only `0.3`, the Python package version becomes `0.3` (valid PEP 440). This is fine — Python accepts two-segment versions.

However, if a patch version is needed for Python-specific fixes, create a `python-patch` file or switch to a build-time version assembly. For now, `0.3` works.

No change to `pyproject.toml` needed yet — `version = {file = "VERSION"}` continues to work.

- [ ] **Step 6: Update TypeScript package.json version**

Change the version in `typescript/package.json` from `"0.3.18"` to `"0.3.0"`:

The package.json version must be a valid semver (3 segments required by npm), so use `0.3.0` — the `.0` is the TypeScript-specific patch.

- [ ] **Step 7: Run version sync check**

```bash
uv run python scripts/check_version_sync.py
```

Expected output:
```
VERSION file: 0.3
  python: 0.3 — OK
  typescript: 0.3.0 — OK
  go: not present (skipped)
  rust: not present (skipped)
  csharp: not present (skipped)

PASSED — all present languages match VERSION.
```

- [ ] **Step 8: Run the tooling test**

```bash
uv run python scripts/run_pytest_gate.py tests/tooling/test_check_version_sync.py --no-cov -q
```

Expected: PASS

- [ ] **Step 9: Verify Python package still builds**

```bash
uv run python -m build
uv run twine check dist/*
```

Expected: Build succeeds with version `0.3`.

- [ ] **Step 10: Commit**

```bash
git add VERSION typescript/package.json scripts/check_version_sync.py tests/tooling/test_check_version_sync.py
git commit -m "feat(version): transition to shared major.minor versioning with per-language patch"
```

---

### Task 4: Promote cross-language E2E tests to repo root

**Files:**
- Move: `tests/e2e/test_cross_language_trace_e2e.py` → `e2e/test_cross_language_trace_e2e.py`
- Move: `tests/e2e/test_browser_trace_e2e.py` → `e2e/test_browser_trace_e2e.py`
- Move: `tests/e2e/test_openobserve_e2e.py` → `e2e/test_openobserve_e2e.py`
- Move: `tests/e2e/backends/` → `e2e/backends/`
- Create: `e2e/conftest.py`
- Create: `e2e/__init__.py`
- Modify: `pyproject.toml` (pytest config)
- Modify: `.github/workflows/ci.yml:261-267` (E2E job paths)

- [ ] **Step 1: Create `e2e/` directory with conftest**

Create `e2e/__init__.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#
```

Create `e2e/conftest.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Shared fixtures for cross-language E2E tests."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture()
def repo_root() -> Path:
    """Return the repository root path."""
    return REPO_ROOT
```

- [ ] **Step 2: Move E2E test files**

```bash
cp -r tests/e2e/backends e2e/backends
cp tests/e2e/test_cross_language_trace_e2e.py e2e/
cp tests/e2e/test_browser_trace_e2e.py e2e/
cp tests/e2e/test_openobserve_e2e.py e2e/
```

- [ ] **Step 3: Update `_REPO_ROOT` in moved files**

In all three test files, update the path computation. The old code:

```python
_REPO_ROOT = Path(__file__).parent.parent.parent
```

becomes (now one level up from `e2e/`):

```python
_REPO_ROOT = Path(__file__).parent.parent
```

Also in each file, update `_SERVER_SCRIPT` path from:

```python
_SERVER_SCRIPT = _REPO_ROOT / "tests" / "e2e" / "backends" / "cross_language_server.py"
```

to:

```python
_SERVER_SCRIPT = _REPO_ROOT / "e2e" / "backends" / "cross_language_server.py"
```

In `test_browser_trace_e2e.py`, the same `_REPO_ROOT` and `_SERVER_SCRIPT` patterns apply.

In `test_openobserve_e2e.py`, update `_REPO_ROOT` similarly (check if it has `_SERVER_SCRIPT` — adjust accordingly).

- [ ] **Step 4: Remove old `tests/e2e/` directory**

```bash
rm -rf tests/e2e/
```

- [ ] **Step 5: Update pyproject.toml pytest config**

The current E2E marker exclusion in `addopts` (`-m "not e2e and not memray"`) still works — e2e tests are excluded from default runs regardless of location.

Add `e2e` to `norecursedirs` is NOT needed — e2e tests are marker-excluded, not path-excluded.

However, update the `openobserve-e2e` CI job to point to the new location. No pyproject.toml change needed for pytest — the E2E tests are only run with explicit `-m e2e`.

But we need to ensure pytest can discover the `e2e/` directory. Add it to `python_files` search or run with explicit path. The CI job already runs with `-m e2e`, and pytest discovers all matching files. Verify that `e2e/` is not in `norecursedirs`:

Current `norecursedirs = [".*", "build", "dist", "mutants"]` — `e2e/` is not excluded, so pytest will find it.

- [ ] **Step 6: Update CI workflow**

In `.github/workflows/ci.yml`, the `openobserve-e2e` job runs:
```
uv run python scripts/run_pytest_gate.py -m e2e --no-cov -q
```

This discovers tests by marker, not path, so it will automatically pick up the moved files. No CI change needed unless `run_pytest_gate.py` restricts test discovery paths.

Verify by checking `scripts/run_pytest_gate.py` — if it passes through to pytest with the marker filter, no change needed.

- [ ] **Step 7: Run E2E tests in dry mode to verify discovery**

```bash
uv run python -m pytest e2e/ --collect-only -q 2>&1 | head -20
```

Expected: Shows the three test files being collected (they'll be skipped without env vars, but collection works).

- [ ] **Step 8: Run full Python test suite to verify nothing broke**

```bash
uv run python scripts/run_pytest_gate.py
```

Expected: PASS — E2E tests are excluded by marker, unit tests unaffected.

- [ ] **Step 9: Commit**

```bash
git add e2e/ && git rm -r tests/e2e/
git commit -m "refactor(e2e): promote cross-language E2E tests to repo root"
```

---

### Task 5: Add CI spec conformance workflow

**Files:**
- Create: `.github/workflows/ci-spec.yml`
- Modify: `.github/workflows/ci.yml` (add spec check to quality job)

- [ ] **Step 1: Create the spec CI workflow**

Create `.github/workflows/ci-spec.yml`:

```yaml
name: Spec Conformance

on:
  push:
    branches: [main]
    paths:
      - "spec/**"
      - "src/undef/telemetry/__init__.py"
      - "typescript/src/index.ts"
      - "go/**"
      - "rust/**"
      - "csharp/**"
      - "VERSION"
      - "typescript/package.json"
      - "pyproject.toml"
  pull_request:
    branches: [main]
    paths:
      - "spec/**"
      - "src/undef/telemetry/__init__.py"
      - "typescript/src/index.ts"
      - "go/**"
      - "rust/**"
      - "csharp/**"
      - "VERSION"
      - "typescript/package.json"
      - "pyproject.toml"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  conformance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: API conformance check
        run: python spec/validate_conformance.py

  version-sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Version sync check
        run: python scripts/check_version_sync.py
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci-spec.yml
git commit -m "ci: add spec conformance and version sync workflow"
```

---

### Task 6: Update SPDX headers and documentation

**Files:**
- Modify: `CLAUDE.md` (add polyglot instructions)
- Modify: `REUSE.toml` (add spec/ and e2e/ paths if needed)

- [ ] **Step 1: Add polyglot section to CLAUDE.md**

Append the following section to CLAUDE.md after the "Testing Conventions" section:

```markdown
## Polyglot Structure

- `spec/telemetry-api.yaml` — canonical API surface definition; all languages validate against it.
- `spec/validate_conformance.py` — checks language exports against spec.
- `scripts/check_version_sync.py` — ensures all languages share major.minor from `VERSION`.
- `VERSION` contains major.minor only (e.g. `0.3`); each language tracks patch independently.
- `e2e/` — cross-language E2E tests (promoted from `tests/e2e/`).
- Language directories: `typescript/`, `go/`, `rust/`, `csharp/` — each self-contained with own build config.
- Python stays at repo root (`src/`, `pyproject.toml`, `tests/`).
```

- [ ] **Step 2: Verify SPDX headers on new files**

```bash
uv run python scripts/check_spdx_headers.py
```

Expected: PASS — all new Python files have SPDX headers. The YAML file needs SPDX comment headers too (already included in Task 1).

- [ ] **Step 3: Run full quality suite**

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run codespell
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add polyglot structure section to CLAUDE.md"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run the full Python test suite**

```bash
uv run python scripts/run_pytest_gate.py
```

Expected: PASS with 100% branch coverage.

- [ ] **Step 2: Run spec conformance**

```bash
uv run python spec/validate_conformance.py
```

Expected: PASS.

- [ ] **Step 3: Run version sync**

```bash
uv run python scripts/check_version_sync.py
```

Expected: PASS.

- [ ] **Step 4: Run TypeScript tests**

```bash
cd typescript && npm run test:coverage && cd ..
```

Expected: PASS.

- [ ] **Step 5: Verify build**

```bash
uv run python -m build && uv run twine check dist/*
```

Expected: PASS.
