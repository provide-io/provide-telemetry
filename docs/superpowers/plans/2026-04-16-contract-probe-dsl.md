# Contract Probe DSL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a step-based contract probe DSL that exercises real public APIs across all 4 languages and catches cross-language drift at integration seams.

**Architecture:** YAML fixture file defines test cases as sequences of operations. Each language implements a ~150-200 LOC interpreter that executes steps and emits JSON results. A Python harness spawns all 4 probes per case and cross-compares outputs.

**Tech Stack:** Python (harness + probe), TypeScript (probe), Go (probe), Rust (probe), YAML (fixtures)

---

### Task 1: Create contract fixtures YAML

**Files:**
- Create: `spec/contract_fixtures.yaml`

- [ ] **Step 1: Write the 6 contract cases**

Create `spec/contract_fixtures.yaml` with all 6 cases from the spec. Each case has `description`, `steps` (list of operations), and `expect` (dotted-path assertions). Use the exact operation names from the spec: `setup`, `setup_invalid`, `shutdown`, `bind_propagation`, `clear_propagation`, `get_trace_context`, `bind_context`, `emit_log`, `capture_log`, `get_runtime_status`.

The traceparent format is `00-{32-char-trace-id}-{16-char-span-id}-01`. Use simple hex strings like `aabbccdd11223344aabbccdd11223344` to avoid secret detection.

- [ ] **Step 2: Validate YAML parses correctly**

```bash
uv run python -c "import yaml; d = yaml.safe_load(open('spec/contract_fixtures.yaml')); print(list(d['contract_cases'].keys()))"
```

Expected: `['propagation_to_logger_correlation', 'trace_field_precedence', 'setup_invalid_overrides', 'shutdown_re_setup', 'baggage_auto_injection', 'propagation_cleanup']`

- [ ] **Step 3: Commit**

```bash
git add spec/contract_fixtures.yaml
git commit -m "feat: add contract probe DSL fixture YAML with 6 cases"
```

---

### Task 2: Python contract probe interpreter

**Files:**
- Create: `spec/probes/contract_probe_python.py`

- [ ] **Step 1: Write the Python interpreter**

The interpreter reads `PROVIDE_CONTRACT_CASE` env var, loads the YAML, finds the case, executes each step using the real public API, and emits JSON to stdout.

Log capture: use `io.StringIO` + `redirect_stderr` to capture structlog JSON output, then parse the last JSON line.

Key imports from the public API:
- `setup_telemetry`, `shutdown_telemetry`
- `get_logger`, `bind_context`, `clear_context`
- `extract_w3c_context`, `bind_propagation_context`, `clear_propagation_context`
- `get_trace_context`, `get_runtime_status`

The interpreter loop is a `match step["op"]` dispatch. For `capture_log`, capture stderr during `emit_log` and parse the JSON. For `setup_invalid`, wrap in try/except and store `{raised: True/False, error: str}`.

SPDX header required. Target ~150 LOC.

- [ ] **Step 2: Verify it runs the first case**

```bash
PROVIDE_CONTRACT_CASE=propagation_to_logger_correlation uv run python spec/probes/contract_probe_python.py
```

Expected: JSON output with `case` and `variables` keys.

- [ ] **Step 3: Commit**

```bash
git add spec/probes/contract_probe_python.py
git commit -m "feat: add Python contract probe interpreter"
```

---

### Task 3: TypeScript contract probe interpreter

**Files:**
- Create: `spec/probes/contract_probe_typescript.ts`

- [ ] **Step 1: Write the TypeScript interpreter**

Same pattern as Python. Read `PROVIDE_CONTRACT_CASE`, load YAML via the `yaml` devDependency, execute steps, emit JSON to stdout.

Log capture: call `setupTelemetry({ consoleOutput: false, logFormat: 'json' })`, use the write hook to capture records into an array, read the last entry for `capture_log`.

Key imports from `../../typescript/src/index.js`:
- `setupTelemetry`, `shutdownTelemetry`, `resetTelemetryState`
- `getLogger`, `bindContext`, `clearContext`
- `extractW3cContext`, `bindPropagationContext`, `clearPropagationContext`
- `getTraceContext`, `getRuntimeStatus`
- `setTraceContext` (NOT used in steps — only the public propagation API)

For `capture_log`: import `makeWriteHook` from `../../typescript/src/logger.js` and collect records. Override the hook to store records in a module-level array.

SPDX header. Target ~150 LOC.

- [ ] **Step 2: Verify it runs**

```bash
cd typescript && PROVIDE_CONTRACT_CASE=propagation_to_logger_correlation npx tsx ../spec/probes/contract_probe_typescript.ts
```

- [ ] **Step 3: Commit**

```bash
git add spec/probes/contract_probe_typescript.ts
git commit -m "feat: add TypeScript contract probe interpreter"
```

---

### Task 4: Go contract probe interpreter

**Files:**
- Create: `spec/probes/contract_probe_go/main.go`

- [ ] **Step 1: Write the Go interpreter**

Same pattern. Read `PROVIDE_CONTRACT_CASE`, load YAML via `gopkg.in/yaml.v3`, execute steps, emit JSON to stdout.

Log capture: create a custom `slog.Handler` that writes JSON to a `bytes.Buffer`. After `emit_log`, parse the buffer for the last JSON record.

Key imports from the top-level telemetry package:
- `telemetry.SetupTelemetry`, `telemetry.ShutdownTelemetry`
- `telemetry.GetLogger`, `telemetry.BindContext`
- `telemetry.ExtractW3CContext`, `telemetry.BindPropagationContext`
- `telemetry.GetTraceContext` (check exact name), `telemetry.GetRuntimeStatus`

For W3C context extraction, construct an `http.Header` from the step's `traceparent`/`baggage` fields and pass to `ExtractW3CContext`.

SPDX header. Target ~200 LOC. Go module path: `github.com/provide-io/provide-telemetry/go`.

- [ ] **Step 2: Verify it runs**

```bash
cd go && PROVIDE_CONTRACT_CASE=propagation_to_logger_correlation go run ../spec/probes/contract_probe_go/main.go
```

- [ ] **Step 3: Commit**

```bash
git add spec/probes/contract_probe_go/main.go
git commit -m "feat: add Go contract probe interpreter"
```

---

### Task 5: Rust contract probe interpreter

**Files:**
- Create: `rust/examples/contract_probe.rs`
- Modify: `rust/Cargo.toml` (add serde_yaml to dev-dependencies)

- [ ] **Step 1: Add serde_yaml dev-dependency**

In `rust/Cargo.toml` under `[dev-dependencies]`, add:
```toml
serde_yaml = "0.9"
```

- [ ] **Step 2: Write the Rust interpreter**

Same pattern. Read `PROVIDE_CONTRACT_CASE` env var, load YAML, execute steps, emit JSON to stdout.

Log capture: use `enable_json_capture_for_tests()` before emitting, then `take_json_capture()` to read the last record.

Key imports from `provide_telemetry`:
- `setup_telemetry`, `shutdown_telemetry`
- `get_logger`, `bind_context`, `clear_context`
- `extract_w3c_context`, `bind_propagation_context` (returns PropagationGuard)
- `get_trace_context`, `get_runtime_status` (if exists)

For PropagationGuard cleanup: store the guard in a variable, drop it explicitly for `clear_propagation`.

SPDX header. Target ~200 LOC. Mark as `[[example]]` in Cargo.toml.

- [ ] **Step 3: Verify it compiles and runs**

```bash
cd rust && PROVIDE_CONTRACT_CASE=propagation_to_logger_correlation cargo run --example contract_probe
```

- [ ] **Step 4: Commit**

```bash
git add rust/examples/contract_probe.rs rust/Cargo.toml rust/Cargo.lock
git commit -m "feat: add Rust contract probe interpreter"
```

---

### Task 6: Harness — run_contract_cases in parity_probe_support.py

**Files:**
- Modify: `spec/parity_probe_support.py`

- [ ] **Step 1: Add contract probe runners**

Add a `_contract_probe_runners()` function (following the pattern of `_runtime_probe_runners()`) that returns `ProbeRunner` instances for each language's contract probe.

- [ ] **Step 2: Add `run_contract_cases()` function**

The function:
1. Loads `spec/contract_fixtures.yaml`
2. For each case (or selected subset):
   a. For each language, spawn the probe with `PROVIDE_CONTRACT_CASE=<id>`
   b. Parse JSON stdout
   c. Validate output shape: `{"case": "...", "variables": {...}}`
   d. For each path in `expect`, resolve the dotted path in each language's variables and compare
   e. Cross-compare all variable paths across languages
3. Print results and return success/failure

Dotted path resolution: `"last_log.trace_id"` → `variables["last_log"]["trace_id"]`. Bracket notation `last_log["baggage.userId"]` → `variables["last_log"]["baggage.userId"]`.

- [ ] **Step 3: Verify the function loads and parses**

```bash
uv run python -c "
import sys; sys.path.insert(0, 'spec')
from parity_probe_support import run_contract_cases
# Just verify it imports without error
print('import OK')
"
```

- [ ] **Step 4: Commit**

```bash
git add spec/parity_probe_support.py
git commit -m "feat: add contract case harness to parity_probe_support"
```

---

### Task 7: Wire --check-contracts into run_behavioral_parity.py

**Files:**
- Modify: `spec/run_behavioral_parity.py`

- [ ] **Step 1: Add --check-contracts argument**

Add `--check-contracts` to the argparse parser. When set, call `run_contract_cases()` from `parity_probe_support`.

- [ ] **Step 2: Verify end-to-end**

```bash
uv run python spec/run_behavioral_parity.py --check-contracts
```

Expected: all 6 cases pass across all 4 languages.

- [ ] **Step 3: Commit**

```bash
git add spec/run_behavioral_parity.py
git commit -m "feat: wire --check-contracts into behavioral parity runner"
```

---

### Task 8: Integration test for the contract harness

**Files:**
- Modify: `tests/tooling/test_run_behavioral_parity.py`

- [ ] **Step 1: Add test for contract case loading**

Add a test that loads `spec/contract_fixtures.yaml` and verifies all 6 expected case IDs are present.

- [ ] **Step 2: Add test for dotted path resolution**

Test the path resolver with nested dicts:
- `"a.b"` on `{"a": {"b": 1}}` → `1`
- `'a["b.c"]'` on `{"a": {"b.c": 2}}` → `2`

- [ ] **Step 3: Commit**

```bash
git add tests/tooling/test_run_behavioral_parity.py
git commit -m "test: add contract harness unit tests"
```

---

## Execution Order

Tasks are mostly sequential since each builds on the previous:

1. **Task 1** — fixtures YAML (foundation)
2. **Tasks 2-5** — probe interpreters (parallel, independent per language)
3. **Task 6** — harness (needs fixtures + at least one probe to test)
4. **Task 7** — CLI wiring (needs harness)
5. **Task 8** — integration tests (needs everything)

Parallelizable: Tasks 2, 3, 4, 5 (one per language).

## Verification

After all tasks, the final gate:

```bash
uv run python spec/run_behavioral_parity.py --check-contracts
```

Must show all 6 cases green across all 4 languages.
