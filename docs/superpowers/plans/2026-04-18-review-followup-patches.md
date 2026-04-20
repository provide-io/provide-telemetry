# Review Follow-Up Patches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore green spec gates after the April 18, 2026 review by closing governance export gaps, fixing strict parity dependency bootstrap, and removing low-risk fixture-coverage false positives.

**Architecture:** Ship the patch in three layers. First, make the public governance surface consistent across Python, TypeScript, and Go so the conformance contract can pass. Second, make the strict parity runner and CI bootstrap agree on Python OTel dependencies. Third, trim fixture-coverage noise by teaching the gate about real probe files and adding exact category-named parity checks in TypeScript. Leave the remaining Rust allowlist burn-down to a separate follow-up plan because it spans a different acceptance surface.

**Tech Stack:** Python, TypeScript, Go, GitHub Actions, pytest, Vitest, `go test`, YAML tooling

---

## File Map

- `src/provide/telemetry/classification.py`
  Add `register_classification_rule()` and `classify_key()` as public helpers.
- `src/provide/telemetry/__init__.py`
  Export the new Python governance helpers through the lazy registry, type-checking imports, and `__all__`.
- `tests/governance/test_classification_module.py`
  Add direct unit coverage for the new Python public helpers.
- `tests/governance/test_strippability.py`
  Assert the new governance helpers are still lazy exports, not eager imports.
- `typescript/src/classification.ts`
  Add `registerClassificationRule()` and `classifyKey()`.
- `typescript/src/index.ts`
  Re-export the new TypeScript helpers from the package barrel.
- `typescript/tests/classification.test.ts`
  Add direct wrapper/accessor tests for the new TypeScript public helpers.
- `go/classification.go`
  Add `RegisterClassificationRule()` and `ClassifyKey()`.
- `go/classification_test.go`
  Add targeted Go tests for the new exported helpers.
- `tests/tooling/test_validate_conformance.py`
  Flip the conformance tooling test from expected-failure to expected-success.
- `ci/install_parity_deps.py`
  Install the Python `otel` extra used by strict runtime-probe cases.
- `tests/tooling/test_ci_workflow_strictness.py`
  Lock in that the parity bootstrap installs the OTel extra.
- `spec/check_fixture_coverage.py`
  Count real probe files for `log_output_format`.
- `typescript/tests/parity.test.ts`
  Add explicit `sampling_signal_validation`, `backpressure_unlimited`, and `health_snapshot` parity blocks.
- `spec/fixture_coverage_allowlist.yaml`
  Remove the TypeScript and Go allowlist entries that become unnecessary after the above changes.
- `tests/tooling/test_check_fixture_coverage.py`
  Assert the removed allowlist entries stay gone from the reported gap set.

## Tasks

### Task 1: Export Python governance convenience helpers

**Files:**
- Modify: `tests/governance/test_classification_module.py`
- Modify: `tests/governance/test_strippability.py`
- Modify: `src/provide/telemetry/classification.py`
- Modify: `src/provide/telemetry/__init__.py`

- [ ] **Step 1: Write the failing Python tests**

Add these tests to `tests/governance/test_classification_module.py` and extend the lazy-registry assertions in `tests/governance/test_strippability.py`:

```python
from provide.telemetry.classification import (
    classify_key,
    register_classification_rule,
)


def test_register_single_rule_wrapper_installs_hook() -> None:
    register_classification_rule(ClassificationRule(pattern="email", classification=DataClass.PII))
    assert pii_mod._classification_hook is not None


def test_classify_key_returns_dataclass_member() -> None:
    register_classification_rule(ClassificationRule(pattern="email", classification=DataClass.PII))
    assert classify_key("email") is DataClass.PII
    assert classify_key("missing") is None
```

```python
assert "register_classification_rule" in _LAZY_REGISTRY
assert "classify_key" in _LAZY_REGISTRY
```

- [ ] **Step 2: Run the Python tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/governance/test_classification_module.py tests/governance/test_strippability.py -q --no-cov
```

Expected: `ImportError` / `AttributeError` for `register_classification_rule` and `classify_key`, or assertion failures because the lazy registry does not expose them yet.

- [ ] **Step 3: Add the Python public helpers and exports**

In `src/provide/telemetry/classification.py`, add the public helpers and export them:

```python
__all__ = [
    "ClassificationPolicy",
    "ClassificationRule",
    "DataClass",
    "classify_key",
    "get_classification_policy",
    "register_classification_rule",
    "register_classification_rules",
    "set_classification_policy",
]


def register_classification_rule(rule: ClassificationRule) -> None:
    """Convenience wrapper for registering a single classification rule."""
    register_classification_rules([rule])


def classify_key(key: str, value: Any | None = None) -> DataClass | None:
    """Return the matching DataClass for key, or None when no rule matches."""
    label = _classify_field(key, value)
    return DataClass(label) if label is not None else None
```

In `src/provide/telemetry/__init__.py`, expose them through type-checking imports, `_register(...)`, and `__all__`:

```python
from provide.telemetry.classification import (
    ClassificationPolicy,
    ClassificationRule,
    DataClass,
    classify_key,
    get_classification_policy,
    register_classification_rule,
    register_classification_rules,
    set_classification_policy,
)
```

```python
_register(
    "provide.telemetry.classification",
    "ClassificationPolicy",
    "ClassificationRule",
    "DataClass",
    "classify_key",
    "get_classification_policy",
    "register_classification_rule",
    "register_classification_rules",
    "set_classification_policy",
)
```

- [ ] **Step 4: Re-run the Python tests**

Run:

```bash
uv run python -m pytest tests/governance/test_classification_module.py tests/governance/test_strippability.py -q --no-cov
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/provide/telemetry/classification.py src/provide/telemetry/__init__.py tests/governance/test_classification_module.py tests/governance/test_strippability.py
git commit -m "fix(python): export governance helper wrappers for conformance parity"
```

---

### Task 2: Export TypeScript governance convenience helpers

**Files:**
- Modify: `typescript/tests/classification.test.ts`
- Modify: `typescript/src/classification.ts`
- Modify: `typescript/src/index.ts`

- [ ] **Step 1: Write the failing TypeScript tests**

Add these tests to `typescript/tests/classification.test.ts`:

```typescript
import {
  _classifyField,
  classifyKey,
  registerClassificationRule,
} from '../src/classification';

it('registerClassificationRule delegates to plural registration', () => {
  registerClassificationRule({ pattern: 'email', classification: 'PII' });
  expect(_classifyField('email', 'alice@example.com')).toBe('PII');
});

it('classifyKey returns the public DataClass value or null', () => {
  registerClassificationRule({ pattern: 'email', classification: 'PII' });
  expect(classifyKey('email', 'alice@example.com')).toBe('PII');
  expect(classifyKey('missing')).toBeNull();
});
```

- [ ] **Step 2: Run the TypeScript tests to verify they fail**

Run:

```bash
cd typescript && npx vitest run tests/classification.test.ts
```

Expected: compile/import failure because `registerClassificationRule` and `classifyKey` are not exported yet.

- [ ] **Step 3: Add the TypeScript public helpers and barrel exports**

In `typescript/src/classification.ts`, add:

```typescript
export function registerClassificationRule(rule: ClassificationRule): void {
  registerClassificationRules([rule]);
}

export function classifyKey(key: string, value?: unknown): DataClass | null {
  return _classifyField(key, value) as DataClass | null;
}
```

In `typescript/src/index.ts`, export them:

```typescript
export {
  classifyKey,
  registerClassificationRule,
  registerClassificationRules,
  setClassificationPolicy,
  getClassificationPolicy,
  resetClassificationForTests,
} from './classification';
```

- [ ] **Step 4: Re-run TypeScript tests and conformance**

Run:

```bash
cd typescript && npx vitest run tests/classification.test.ts
uv run python spec/validate_conformance.py --lang typescript
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add typescript/src/classification.ts typescript/src/index.ts typescript/tests/classification.test.ts
git commit -m "fix(typescript): export governance helper wrappers for conformance parity"
```

---

### Task 3: Export Go governance convenience helpers

**Files:**
- Modify: `go/classification_test.go`
- Modify: `go/classification.go`

- [ ] **Step 1: Write the failing Go tests**

Add these tests to `go/classification_test.go`:

```go
func TestRegisterClassificationRule_InstallsHook(t *testing.T) {
	resetClassification(t)
	resetPII(t)

	RegisterClassificationRule(ClassificationRule{Pattern: "email", Classification: DataClassPII})

	_piiMu.RLock()
	hook := _classificationHook
	_piiMu.RUnlock()
	if hook == nil {
		t.Fatal("expected hook after RegisterClassificationRule")
	}
}

func TestClassifyKey_ReturnsPointerOrNil(t *testing.T) {
	resetClassification(t)
	RegisterClassificationRule(ClassificationRule{Pattern: "email", Classification: DataClassPII})

	label := ClassifyKey("email")
	if label == nil || *label != DataClassPII {
		t.Fatalf("expected PII pointer, got %#v", label)
	}
	if ClassifyKey("missing") != nil {
		t.Fatal("expected nil for unmatched key")
	}
}
```

- [ ] **Step 2: Run the Go tests to verify they fail**

Run:

```bash
go test ./... -run 'Test(RegisterClassificationRule_InstallsHook|ClassifyKey_ReturnsPointerOrNil)' -count=1
```

Expected: build failure because `RegisterClassificationRule` and `ClassifyKey` do not exist yet.

- [ ] **Step 3: Add the Go exported helpers**

In `go/classification.go`, add:

```go
func RegisterClassificationRule(rule ClassificationRule) {
	RegisterClassificationRules([]ClassificationRule{rule})
}

func ClassifyKey(key string) *DataClass {
	label := _classifyField(key, nil)
	if label == "" {
		return nil
	}
	class := DataClass(label)
	return &class
}
```

- [ ] **Step 4: Re-run Go tests and conformance**

Run:

```bash
go test ./... -run 'Test(RegisterClassificationRule_InstallsHook|ClassifyKey_ReturnsPointerOrNil|Test(Classification|PolicyAction|LookupPolicyAction))' -count=1
uv run python spec/validate_conformance.py --lang go
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add go/classification.go go/classification_test.go
git commit -m "fix(go): export governance helper wrappers for conformance parity"
```

---

### Task 4: Turn the conformance gate green again

**Files:**
- Modify: `tests/tooling/test_validate_conformance.py`

- [ ] **Step 1: Replace the expected-failure tooling test with an expected-success assertion**

Replace `test_conformance_governance_gaps_reported()` with:

```python
def test_conformance_succeeds_with_governance_exports_present() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"Expected conformance to pass:\\nstdout: {result.stdout}\\nstderr: {result.stderr}"
    )
    assert "MISSING [governance]" not in result.stdout
```

- [ ] **Step 2: Run the tooling test before touching anything else**

Run:

```bash
uv run python -m pytest tests/tooling/test_validate_conformance.py -q --no-cov
```

Expected: PASS once Tasks 1-3 are already complete.

- [ ] **Step 3: Run the full conformance command**

Run:

```bash
uv run python spec/validate_conformance.py
```

Expected: all four languages print `OK` or only documented kind notes, and exit code `0`.

- [ ] **Step 4: Commit**

```bash
git add tests/tooling/test_validate_conformance.py
git commit -m "test(tooling): require governance conformance to pass"
```

---

### Task 5: Align strict parity bootstrap with runtime-probe dependencies

**Files:**
- Modify: `tests/tooling/test_ci_workflow_strictness.py`
- Modify: `ci/install_parity_deps.py`

- [ ] **Step 1: Add a tooling test that locks in the Python OTel extra**

Add this to `tests/tooling/test_ci_workflow_strictness.py`:

```python
CI_PARITY_BOOTSTRAP = REPO_ROOT / "ci" / "install_parity_deps.py"


def test_parity_bootstrap_installs_python_otel_extra() -> None:
    bootstrap = CI_PARITY_BOOTSTRAP.read_text(encoding="utf-8")
    assert '"uv", "sync", "--group", "dev", "--extra", "otel"' in bootstrap
```

- [ ] **Step 2: Run the tooling test to verify it fails**

Run:

```bash
uv run python -m pytest tests/tooling/test_ci_workflow_strictness.py -q --no-cov
```

Expected: FAIL because the bootstrap still installs only `--group dev`.

- [ ] **Step 3: Update the parity bootstrap**

In `ci/install_parity_deps.py`, change the Python dependency install to:

```python
_run(["uv", "sync", "--group", "dev", "--extra", "otel"], _REPO_ROOT)
```

- [ ] **Step 4: Re-run the tooling test and the strict parity command**

Run:

```bash
uv run python -m pytest tests/tooling/test_ci_workflow_strictness.py -q --no-cov
python ci/install_parity_deps.py
uv run python spec/run_behavioral_parity.py
```

Expected: tooling test PASS; bootstrap completes; strict parity command exits `0` without the `opentelemetry-sdk[otlp] extra` error.

- [ ] **Step 5: Commit**

```bash
git add ci/install_parity_deps.py tests/tooling/test_ci_workflow_strictness.py
git commit -m "fix(ci): install python otel extra for strict parity probes"
```

---

### Task 6: Remove low-risk fixture-coverage false positives

**Files:**
- Modify: `tests/tooling/test_check_fixture_coverage.py`
- Modify: `spec/check_fixture_coverage.py`
- Modify: `typescript/tests/parity.test.ts`
- Modify: `spec/fixture_coverage_allowlist.yaml`

- [ ] **Step 1: Add failing coverage assertions for the false-positive gaps**

Add this to `tests/tooling/test_check_fixture_coverage.py`:

```python
def test_check_fixture_coverage_no_longer_reports_ts_and_go_false_positives() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )
    assert "typescript: missing 'backpressure_unlimited'" not in result.stdout
    assert "typescript: missing 'sampling_signal_validation'" not in result.stdout
    assert "typescript: missing 'health_snapshot'" not in result.stdout
    assert "typescript: missing 'log_output_format'" not in result.stdout
    assert "go: missing 'log_output_format'" not in result.stdout
```

- [ ] **Step 2: Run the coverage tooling test to verify it fails**

Run:

```bash
uv run python -m pytest tests/tooling/test_check_fixture_coverage.py -q --no-cov
```

Expected: FAIL with the current false-positive gaps still present.

- [ ] **Step 3: Teach the fixture gate about real probe files and add exact TS parity category blocks**

In `spec/check_fixture_coverage.py`, extend `_LANGUAGE_FILES`:

```python
    "typescript": [
        _REPO_ROOT / "typescript" / "tests" / "parity.test.ts",
        _REPO_ROOT / "typescript" / "tests" / "endpoint.test.ts",
        _REPO_ROOT / "spec" / "probes" / "emit_log_typescript.ts",
    ],
```

```python
    "go": [
        _REPO_ROOT / "go" / "parity_test.go",
        _REPO_ROOT / "go" / "parity_backpressure_test.go",
        _REPO_ROOT / "go" / "parity_cardinality_test.go",
        _REPO_ROOT / "go" / "parity_config_test.go",
        _REPO_ROOT / "go" / "parity_health_test.go",
        _REPO_ROOT / "go" / "parity_pii_test.go",
        _REPO_ROOT / "go" / "parity_propagation_test.go",
        _REPO_ROOT / "go" / "parity_sampling_test.go",
        _REPO_ROOT / "go" / "parity_schema_test.go",
        _REPO_ROOT / "go" / "parity_slo_test.go",
        _REPO_ROOT / "go" / "parity_endpoint_test.go",
        _REPO_ROOT / "spec" / "probes" / "emit_log_go" / "main.go",
    ],
```

In `typescript/tests/parity.test.ts`, add explicit category-named parity blocks:

```typescript
import { getHealthSnapshot } from '../src/health';
import { setQueuePolicy, tryAcquire, release } from '../src/backpressure';

describe('parity: sampling_signal_validation', () => {
  it('rejects unknown signal name', () => {
    expect(() => shouldSample('invalid')).toThrow();
  });

  it('accepts valid signal names', () => {
    expect(() => shouldSample('logs')).not.toThrow();
    expect(() => shouldSample('traces')).not.toThrow();
    expect(() => shouldSample('metrics')).not.toThrow();
  });
});

describe('parity: backpressure_unlimited', () => {
  it('queue size 0 remains unlimited', () => {
    setQueuePolicy({ maxLogs: 0, maxTraces: 0, maxMetrics: 0 });
    for (let i = 0; i < 100; i++) {
      const ticket = tryAcquire('logs');
      expect(ticket).not.toBeNull();
      if (ticket) release(ticket);
    }
  });
});

describe('parity: health_snapshot', () => {
  it('returns a snapshot object with numeric counters', () => {
    const snap = getHealthSnapshot();
    expect(typeof snap.logsEmitted).toBe('number');
    expect(typeof snap.logsDropped).toBe('number');
  });
});
```

- [ ] **Step 4: Remove the obsolete allowlist entries**

Delete these entries from `spec/fixture_coverage_allowlist.yaml`:

```yaml
- lang: typescript
  category: backpressure_unlimited
...
- lang: typescript
  category: sampling_signal_validation
...
- lang: typescript
  category: health_snapshot
...
- lang: typescript
  category: log_output_format
...
- lang: go
  category: log_output_format
...
```

- [ ] **Step 5: Re-run the coverage gate and targeted TypeScript tests**

Run:

```bash
uv run python -m pytest tests/tooling/test_check_fixture_coverage.py -q --no-cov
cd typescript && npx vitest run tests/parity.test.ts
uv run python spec/check_fixture_coverage.py
```

Expected: all PASS; those five entries disappear from the reported gaps.

- [ ] **Step 6: Commit**

```bash
git add spec/check_fixture_coverage.py spec/fixture_coverage_allowlist.yaml tests/tooling/test_check_fixture_coverage.py typescript/tests/parity.test.ts
git commit -m "fix(spec): remove low-risk fixture coverage false positives"
```

---

## Deferred Follow-Up

The remaining Rust allowlist entries are a separate subsystem-sized cleanup and should be planned independently after the six tasks above land. That follow-up should decide, category by category, whether to:

1. add explicit Rust parity tests,
2. expand the fixture gate to scan the Rust tests that already exercise the behavior, or
3. keep a smaller, more honest allowlist for type-level or probe-level gaps such as `log_output_format`.

Do not fold that work into this patch unless the current branch has spare review bandwidth; the high-value outcome here is restoring green conformance and strict parity gates first.
