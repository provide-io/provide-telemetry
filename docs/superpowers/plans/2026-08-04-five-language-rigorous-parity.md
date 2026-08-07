# Five-Language Rigorous Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Python, TypeScript, Go, Rust, and C# conform to one executable telemetry contract, including an OTel-free C# core and a separate OpenTelemetry integration package.

**Architecture:** The canonical YAML schema and literal fixtures define externally observable behavior. Each SDK validates and atomically publishes immutable runtime generations, processes signals through the same ordered policy pipeline, emits canonical local records and receipts, and delegates optional transport through an owned backend boundary. Cross-language probes, artifact consumers, collector tests, coverage, race, and mutation gates provide release evidence.

**Tech Stack:** Python 3.11+ with pytest/uv, TypeScript ESM with Node/Vitest/npm, Go with `go test -race`, Rust with Cargo, C# on .NET 10 with xUnit/Coverlet/Stryker.NET 4.16.0, OpenTelemetry OTLP, YAML fixtures, and GitHub Actions.

## Global Constraints

- Target release is `0.8`.
- The canonical contract takes precedence over legacy behavior.
- Remove legacy C# environment names and emit canonical snake_case local fields only.
- `Provide.Telemetry` has no OpenTelemetry, exporter, or Microsoft dependency injection package references.
- `Provide.Telemetry.OpenTelemetry` depends on `Provide.Telemetry`; core never references the integration assembly.
- Signal order is consent, sampling, backpressure, recursive hardening, classification and PII, receipts, canonical local record, optional backend export, health, then ticket release.
- Receipt payload is UTF-8 `receipt_id|timestamp|field_path|action|original_hash` and is signed with lowercase HMAC-SHA256.
- Receipt IDs are lowercase canonical UUID text; timestamps are UTC RFC 3339 with exactly three fractional-second digits and `Z`; actions are lowercase contract enum values.
- `original_hash` is lowercase SHA-256 over RFC 8785 JCS after normalization to null, booleans, finite binary64 numbers, Unicode strings, ordered arrays, and string-keyed objects; unsupported and non-finite scalars normalize to invariant strings.
- RFC 8785 object-property ordering uses lexicographic UTF-16 code-unit order.
- Production receipt delivery is synchronous, keeps no library-owned production buffer, and requires a configured sink whenever receipts are enabled outside test mode.
- Test receipt collectors have a fixed 1,024-entry capacity.
- Sink rejection or failure increments canonical `receipt_failures` without logging recursively; this expands the shared health snapshot from 25 to 26 fields.
- Cycles and uninspectable composite values harden to `"***"`.
- Setup validates a complete snapshot and never clamps invalid configuration.
- Runtime publication occurs only after logging and policy subsystems accept the same generation.
- Flush and shutdown start independent signal drains together and share one absolute deadline.
- Host-owned providers are never shut down or disposed by the SDK.
- C# owned code must reach 100% line and branch coverage and reject surviving owned-code mutants; any framework-glue exemption requires a reviewed reason.
- Before each production change, search for an implementation, characterize it, and skip or narrow the production edit when the existing behavior already passes the new contract test.
- Preserve the pre-existing user modification to `rust/src/resilience_state_tests.rs`; do not stage or rewrite it unless a later explicit user request puts it in scope.

---

## File and Interface Map

- `spec/telemetry-api.yaml` owns names, types, defaults, applicability, canonical field order, and result shapes.
- `spec/receipt_fixtures.yaml` owns fixed JCS, digest, payload, and HMAC vectors.
- `spec/*_fixtures.yaml` owns literal behavioral, runtime, and contract cases; `spec/fixture_test_ids.yaml` maps each required category to executable evidence in all five languages.
- `spec/check_config_parity.py` compares probe output with the schema rather than parsing source text.
- `spec/probes/*` and `csharp/probes/*` expose config, runtime, contract, and local-record behavior at process boundaries.
- Python `src/provide/telemetry/_lifecycle.py` owns lifecycle serialization and generation publication; `receipts.py` owns JCS and `ReceiptSink`.
- TypeScript `typescript/src/async-storage.ts` owns ESM-safe `AsyncLocalStorage`; `receipts.ts` owns JCS and `ReceiptSink`.
- Go `go/runtime_generation.go` owns atomic immutable runtime generations; `go/internal/piicore/pii.go` owns reflective traversal; `go/receipts.go` owns JCS and `ReceiptSink`.
- Rust `rust/src/receipts.rs` owns JCS and `ReceiptSink`; `rust/src/pii.rs` owns normalization and hardening.
- C# `csharp/src/Provide.Telemetry` is the dependency-free core; `csharp/src/Provide.Telemetry.OpenTelemetry` owns OTel providers, bridges, resilient exporters, and provider drains.
- C# core owns `ITelemetryBackend`, `TelemetryBackendRegistry`, `CanonicalLogRecord`, `IReceiptSink`, `LifecycleGeneration`, and `ResilienceExecutor`; only the backend interfaces cross into the integration package.

### Task 1: Make the canonical contract explicit and strict for five languages

**Files:**
- Modify: `spec/telemetry-api.yaml`
- Modify: `spec/check_fixture_test_ids.py`
- Modify: `spec/fixture_test_ids.yaml`
- Modify: `spec/run_behavioral_parity.py`
- Modify: `spec/parity_probe_support.py`
- Modify: `spec/_runtime_probe.py`
- Modify: `spec/contract_probe_harness.py`
- Create: `spec/check_config_parity.py`
- Create: `spec/probes/config_probe_python.py`
- Create: `spec/probes/config_probe_typescript.ts`
- Create: `spec/probes/config_probe_go/main.go`
- Create: `rust/examples/config_probe.rs`
- Create: `csharp/probes/ConfigProbe/ConfigProbe.csproj`
- Create: `csharp/probes/ConfigProbe/Program.cs`
- Modify: `.github/workflows/ci-contracts.yml`
- Modify: `.github/workflows/ci-spec.yml`
- Test: `tests/tooling/test_behavioral_parity_coverage.py`
- Test: `tests/tooling/test_validate_conformance.py`

**Interfaces:**
- Consumes: current four-language fixture ID mapping and the existing C# behavioral, runtime, output, and contract probes.
- Produces: `REQUIRED_LANGUAGES = ("python", "typescript", "go", "rust", "csharp")`; a `config_defaults[*].applicability: list[str]` field; `spec/check_config_parity.py --language <name> [--strict]`; strict probe execution that fails when any selected runtime is unavailable.

- [ ] **Step 1: Characterize existing C# discovery before editing production code**

Run:

```bash
rg -n 'LANGUAGES|csharp|dotnet|skip' spec/check_fixture_test_ids.py spec/run_behavioral_parity.py spec/parity_probe_support.py spec/_runtime_probe.py spec/contract_probe_harness.py
python spec/check_fixture_test_ids.py
```

Expected: the parity runners already mention C#, while the fixture-ID checker reports only Python, TypeScript, Go, and Rust. Record the exact current output in the task commit message; retain existing C# runner support instead of duplicating it.

- [ ] **Step 2: Write failing strictness and applicability tests**

```python
def test_required_languages_include_csharp() -> None:
    from spec.check_fixture_test_ids import REQUIRED_LANGUAGES

    assert REQUIRED_LANGUAGES == (
        "python", "typescript", "go", "rust", "csharp"
    )


def test_every_config_default_declares_applicability(api_spec: dict) -> None:
    for name, entry in api_spec["config_defaults"].items():
        assert entry["applicability"], name
        assert set(entry["applicability"]) <= {
            "python", "typescript", "go", "rust", "csharp"
        }
```

- [ ] **Step 3: Run the tests and confirm the expected red state**

Run:

```bash
uv run pytest tests/tooling/test_behavioral_parity_coverage.py tests/tooling/test_validate_conformance.py -q
```

Expected: Python fails because `REQUIRED_LANGUAGES`, C# fixture mappings, or applicability is absent.

- [ ] **Step 4: Implement strict five-language resolution**

Use this checker shape:

```python
REQUIRED_LANGUAGES = ("python", "typescript", "go", "rust", "csharp")


def require_runtime(language: str, executable: str | None) -> str:
    if executable is None:
        raise RuntimeError(f"required parity runtime unavailable: {language}")
    return executable
```

Add `applicability` to every config entry, add a real C# test or probe ID to every fixture mapping, and remove anchor-only IDs. In both workflows, install .NET 10 before invoking any five-language gate:

```yaml
- uses: actions/setup-dotnet@v4
  with:
    dotnet-version: 10.0.x
- run: python spec/check_fixture_test_ids.py
- run: python spec/run_behavioral_parity.py --strict
```

Each config probe must instantiate the language's public default config and emit actual observed metadata in this exact shape; it must not copy expected values from YAML:

```json
{"language":"python","entries":{"logging.level":{"type":"string","default":"INFO","applicable":true}}}
```

The comparator loads `telemetry-api.yaml`, selects entries whose applicability contains the requested language, and reports an exact diff of `(name, type, default, applicable)` tuples. `--strict` converts a missing runtime or probe into exit code 1.

- [ ] **Step 5: Run the contract foundation gate**

Run:

```bash
uv run pytest tests/tooling/test_behavioral_parity_coverage.py tests/tooling/test_validate_conformance.py -q
python spec/check_fixture_test_ids.py
python spec/run_behavioral_parity.py --strict
python spec/check_config_parity.py --language python
(cd rust && cargo check --example config_probe)
dotnet build csharp/probes/ConfigProbe/ConfigProbe.csproj
```

Expected: all commands pass, parity gates report five required languages, and the Python, Rust, and C# config probes build or match. If the local .NET runtime is unavailable, install .NET 10 before continuing; strict mode must not convert absence into a skip.

- [ ] **Step 6: Commit the strict contract foundation**

```bash
git add spec rust/examples/config_probe.rs csharp/probes/ConfigProbe .github/workflows/ci-contracts.yml .github/workflows/ci-spec.yml tests/tooling
git commit -m "test: require executable parity evidence for five SDKs"
```

### Task 2: Define canonical receipt, JCS, health, and signal-order fixtures

**Files:**
- Create: `spec/receipt_fixtures.yaml`
- Create: `spec/pipeline_fixtures.yaml`
- Modify: `spec/telemetry-api.yaml`
- Create: `tests/tooling/test_receipt_fixtures.py`

**Interfaces:**
- Consumes: the schema applicability model from Task 1.
- Produces: canonical global health field `receipt_failures: uint64`; receipt fixture fields `normalized`, `canonical_json`, `original_hash`, `payload`, and `signature`; literal pipeline event sequence consumed by each language test before Task 16 registers the new strict categories.

- [ ] **Step 1: Confirm no equivalent literal vectors already exist**

Run:

```bash
rg -n 'RFC ?8785|canonical_json|receipt_failures|signal_pipeline_order|receipt_signing' spec tests typescript/tests go rust csharp/tests
```

Expected: no shared literal JCS/HMAC fixture and no canonical `receipt_failures` field. If a complete vector exists, move it into `spec/receipt_fixtures.yaml` and delete the duplicate rather than adding a second source.

- [ ] **Step 2: Add a failing fixture self-test**

```python
import hashlib
import hmac
import json
from pathlib import Path

import yaml


def test_receipt_vectors_are_self_consistent() -> None:
    data = yaml.safe_load(Path("spec/receipt_fixtures.yaml").read_text())
    for case in data["cases"]:
        assert json.loads(case["canonical_json"]) == case["normalized"]
        assert hashlib.sha256(case["canonical_json"].encode()).hexdigest() == case["original_hash"]
        assert hmac.new(
            case["key"].encode(), case["payload"].encode(), hashlib.sha256
        ).hexdigest() == case["signature"]
        assert case["payload"] == "|".join(
            [case["receipt_id"], case["timestamp"], case["field_path"],
             case["action"], case["original_hash"]]
        )


def test_pipeline_vectors_release_once_and_preserve_prefix_order() -> None:
    data = yaml.safe_load(Path("spec/pipeline_fixtures.yaml").read_text())
    canonical = data["events"]
    for case in data["cases"]:
        assert case["expected"].count("release") == 1
        assert [event for event in canonical if event in case["expected"]] == case["expected"]
```

Also make the schema self-test expect `receipt_failures` and exactly 26 serialized health fields.

- [ ] **Step 3: Run the fixture and health tests to verify failure**

Run:

```bash
uv run pytest tests/tooling/test_receipt_fixtures.py tests/tooling/test_validate_conformance.py -q
```

Expected: the fixture test fails because the file is absent and the schema test fails because `receipt_failures` is absent.

- [ ] **Step 4: Add fixed vectors and contract fields**

Start the fixture with exact deterministic values and generate its expected digests once with the self-test helper:

```yaml
version: 1
cases:
  - id: nested_unicode_and_number
    key: parity-secret
    input:
      z: [true, null, "é"]
      a: 1.5
    normalized:
      a: 1.5
      z: [true, null, "é"]
    canonical_json: '{"a":1.5,"z":[true,null,"é"]}'
    receipt_id: 018f47a2-6b7c-7d8e-9f10-111213141516
    timestamp: '2026-08-04T12:34:56.789Z'
    field_path: user.profile
    action: redact
    original_hash: fea3d4b3eb8f3219bf751b664a930bb41758a129b864bbd74f79d399e9aa9de3
    payload: '018f47a2-6b7c-7d8e-9f10-111213141516|2026-08-04T12:34:56.789Z|user.profile|redact|fea3d4b3eb8f3219bf751b664a930bb41758a129b864bbd74f79d399e9aa9de3'
    signature: 9005d50fd071ef627c56290c5b8a639ee748fea3d3a5e3c89eed8fcf19e82c11
```

Add cases for negative zero, escaped controls, astral Unicode, non-finite normalization, nested arrays, sorted object keys, sink acceptance, sink rejection, and sink exception. Derive each digest with the self-test's `hashlib` and `hmac` expressions and commit the resulting lowercase literals. Create `pipeline_fixtures.yaml` with `events: [consent, sampling, backpressure, hardening, pii, receipt, local, backend, health, release]` and exit cases for consent rejection, sampling rejection, queue rejection, local-only success, backend success, and backend failure.

- [ ] **Step 5: Run fixture schema checks**

Run:

```bash
uv run pytest tests/tooling/test_receipt_fixtures.py tests/tooling/test_validate_conformance.py -q
```

Expected: the vectors are self-consistent, the schema exposes 26 health fields, and the pipeline file has one ordered release event on every exit case.

- [ ] **Step 6: Commit the literal contract**

```bash
git add spec tests/tooling/test_receipt_fixtures.py
git commit -m "spec: define canonical governance and pipeline vectors"
```

### Task 3: Make TypeScript scoped storage safe in packed ESM artifacts

**Files:**
- Create: `typescript/src/async-storage.ts`
- Modify: `typescript/src/context.ts`
- Modify: `typescript/src/tracing.ts`
- Modify: `typescript/src/propagation.ts`
- Modify: `typescript/src/index.ts`
- Modify: `typescript/tests/context.test.ts`
- Modify: `typescript/tests/tracing.test.ts`
- Modify: `typescript/tests/propagation.await-init.test.ts`
- Modify: `typescript/tests/propagation.esm-load.test.ts`
- Modify: `typescript/tests/propagation.module-scope-await.test.ts`
- Modify: `typescript/tests/setup-async.test.ts`
- Create: `typescript/tests/packed-esm-context.mjs`
- Modify: `ci/verify-npm-consumer-package.sh`

**Interfaces:**
- Consumes: Node ESM packaging and the existing context, trace-context, and propagation store value types.
- Produces: `createAsyncLocalStorage<T>(): AsyncLocalStorage<T>` from `src/async-storage.ts`; no production `require('node:async_hooks')`; packed-artifact concurrent context retention.

- [ ] **Step 1: Reproduce the published-artifact failure**

Run:

```bash
rg -n "require\(['\"]node:async_hooks|AsyncLocalStorage" typescript/src typescript/dist
(cd typescript && npm run build)
node --input-type=module -e "import('./typescript/dist/index.js').then(async t => console.log(await Promise.all([t.withLogContext({request_id:'a'},async()=>{await Promise.resolve();return t.getLogContext().request_id}),t.withLogContext({request_id:'b'},async()=>{await Promise.resolve();return t.getLogContext().request_id})])))"
```

Expected: source contains CommonJS `require`, and the artifact probe returns missing or crossed context rather than `["a","b"]`.

- [ ] **Step 2: Add failing concurrent and rejection-restoration tests**

```typescript
it('keeps concurrent ESM contexts isolated until callbacks settle', async () => {
  const seen = await Promise.all(['a', 'b'].map(request_id =>
    withLogContext({ request_id }, async () => {
      await Promise.resolve()
      return getLogContext().request_id
    })))
  expect(seen).toEqual(['a', 'b'])
})

it('restores the predecessor after an async callback rejects', async () => {
  await withLogContext({ request_id: 'outer' }, async () => {
    await expect(withLogContext({ request_id: 'inner' }, async () => {
      await Promise.resolve()
      throw new Error('boom')
    })).rejects.toThrow('boom')
    expect(getLogContext().request_id).toBe('outer')
  })
})
```

The packed script imports only the tarball-installed package and asserts the same two values with `node:assert/strict`.

- [ ] **Step 3: Run the source and packed tests to verify failure**

Run:

```bash
npm --prefix typescript test -- --run tests/context.test.ts tests/tracing.test.ts
bash ci/verify-npm-consumer-package.sh
```

Expected: at least the packed ESM concurrency assertion fails because no live `AsyncLocalStorage` backs the published module.

- [ ] **Step 4: Add one ESM-safe storage loader and use it everywhere**

```typescript
import type { AsyncLocalStorage as AsyncLocalStorageType } from 'node:async_hooks'

type AsyncLocalStorageConstructor = new <T>() => AsyncLocalStorageType<T>
const nodeBuiltin = 'node:' + 'async_hooks'
const { AsyncLocalStorage } = await import(nodeBuiltin) as {
  AsyncLocalStorage: AsyncLocalStorageConstructor
}

export function createAsyncLocalStorage<T>(): AsyncLocalStorageType<T> {
  return new AsyncLocalStorage<T>()
}
```

Replace the three local loaders with `createAsyncLocalStorage<T>()`. Delete `awaitPropagationInit` and the fire-and-forget initialization path; ESM module evaluation now completes storage initialization before public functions run. Rewrite the four tests that enforce the former no-top-level-await fallback so they assert immediate initialized storage in the ESM artifact.

- [ ] **Step 5: Verify source and packed ESM behavior**

Run:

```bash
npm --prefix typescript test -- --run tests/context.test.ts tests/tracing.test.ts tests/propagation.test.ts
npm --prefix typescript run build
bash ci/verify-npm-consumer-package.sh
```

Expected: all commands pass, the packed test observes `['a', 'b']`, and `rg -n "require\(['\"]node:async_hooks" typescript/src typescript/dist` returns no matches.

- [ ] **Step 6: Commit the ESM context repair**

```bash
git add typescript/src typescript/tests ci/verify-npm-consumer-package.sh
git commit -m "fix(ts): preserve scoped context in ESM artifacts"
```

### Task 4: Implement canonical TypeScript receipts and recursive hardening

**Files:**
- Modify: `typescript/src/hash.ts`
- Modify: `typescript/src/receipts.ts`
- Modify: `typescript/src/pii.ts`
- Modify: `typescript/src/health.ts`
- Modify: `typescript/src/config.ts`
- Modify: `typescript/src/logger.ts`
- Modify: `typescript/src/otel-logs.ts`
- Modify: `typescript/package.json`
- Modify: `typescript/package-lock.json`
- Create: `typescript/tests/receipt-fixtures.test.ts`
- Modify: `typescript/tests/receipts.test.ts`
- Modify: `typescript/tests/pii.test.ts`
- Modify: `typescript/tests/health.test.ts`
- Create: `typescript/tests/signal-pipeline-order.test.ts`

**Interfaces:**
- Consumes: `spec/receipt_fixtures.yaml` and the canonical signal order from Task 2.
- Produces: `hmacSha256Hex(key: Uint8Array, message: Uint8Array): string`; `ReceiptSink { emit(receipt: RedactionReceipt): boolean }`; `TestReceiptCollector` capped at 1,024; `HealthSnapshot.receipt_failures`.

- [ ] **Step 1: Characterize the existing receipt path and dependency skew**

Run:

```bash
rg -n 'sha256Hex|HMAC|receipt|buffer|collector|0\.220|0\.221' typescript/src typescript/tests typescript/package.json
```

Expected: signing hashes a key/payload concatenation instead of HMAC, production has no required sink, and OTel exporter peer/dev versions differ.

- [ ] **Step 2: Add failing vector, sink, and traversal tests**

```typescript
it.each(receiptCases)('matches receipt vector $id', vector => {
  const receipt = signReceipt(vector.input, {
    key: new TextEncoder().encode(vector.key),
    receipt_id: vector.receipt_id,
    timestamp: vector.timestamp,
  })
  expect(receipt.original_hash).toBe(vector.original_hash)
  expect(receipt.signature).toBe(vector.signature)
})

it('counts rejection without recursively logging', () => {
  const sink: ReceiptSink = { emit: () => false }
  emitReceipt(makeReceipt(), sink)
  expect(getHealth().receipt_failures).toBe(1)
  expect(capturedLogs).toEqual([])
})

it('redacts arrays, objects, and cycles before capture', () => {
  const value: Record<string, unknown> = { items: [{ password: 'secret' }] }
  value.self = value
  expect(harden(value)).toEqual({ items: [{ password: '***' }], self: '***' })
})

it.each(loadPipelineCases())('uses canonical stages for $id', fixture => {
  const observer = new RecordingPipelineObserver()
  processSignal(fixture.input, observer)
  expect(observer.events).toEqual(fixture.expected)
})
```

- [ ] **Step 3: Verify the tests fail for the expected reasons**

Run:

```bash
npm --prefix typescript test -- --run tests/receipt-fixtures.test.ts tests/receipts.test.ts tests/pii.test.ts tests/health.test.ts
```

Expected: vector signature, sink configuration, cycle hardening, and `receipt_failures` assertions fail.

- [ ] **Step 4: Implement HMAC, JCS normalization, bounded test collection, and sink accounting**

Use the public shapes below and keep the pure-JavaScript hash path browser-safe:

```typescript
export interface ReceiptSink {
  emit(receipt: RedactionReceipt): boolean
}

export class TestReceiptCollector implements ReceiptSink {
  readonly receipts: RedactionReceipt[] = []
  emit(receipt: RedactionReceipt): boolean {
    if (this.receipts.length === 1024) this.receipts.shift()
    this.receipts.push(receipt)
    return true
  }
}

export function emitReceipt(receipt: RedactionReceipt, sink: ReceiptSink): void {
  try {
    if (!sink.emit(receipt)) incrementReceiptFailures()
  } catch {
    incrementReceiptFailures()
  }
}
```

Implement RFC 8785 object-key ordering, JSON escaping, binary64 rendering, and `hmacSha256Hex` in `hash.ts`. Reject enabled production receipts without `receiptSink`. Traverse arrays and plain objects through a `WeakSet<object>`; a repeated or unsupported composite returns `"***"`. Apply hardening before logger capture and OTel export. Align every OTel exporter package to the same `0.221.x` release line in peer and dev dependencies.

- [ ] **Step 5: Run the TypeScript quality gate**

Run:

```bash
npm --prefix typescript test -- --run tests/receipt-fixtures.test.ts tests/receipts.test.ts tests/pii.test.ts tests/health.test.ts
npm --prefix typescript test
npm --prefix typescript run lint
npm --prefix typescript run typecheck
npm --prefix typescript run build
bash ci/verify-npm-consumer-package.sh
```

Expected: all commands pass and `npm --prefix typescript ls` reports one compatible exporter version line.

- [ ] **Step 6: Commit TypeScript governance parity**

```bash
git add typescript
git commit -m "feat(ts): enforce canonical governance receipts"
```

### Task 5: Publish immutable Go runtime and logger generations

**Files:**
- Create: `go/runtime_generation.go`
- Modify: `go/runtime.go`
- Modify: `go/runtime_facade.go`
- Modify: `go/setup.go`
- Modify: `go/logger.go`
- Modify: `go/multi_handler.go`
- Modify: `go/health.go`
- Create: `go/runtime_generation_test.go`
- Modify: `go/runtime_reconfigure_test.go`
- Modify: `go/runtime_reconfigure_logging_test.go`
- Modify: `go/runtime_hotreload_test.go`

**Interfaces:**
- Consumes: validated `TelemetryConfig`, current logger construction, and policy application functions.
- Produces: `runtimeGeneration { number uint64; config *TelemetryConfig; logger *slog.Logger }`; `loadRuntimeGeneration() runtimeGeneration`; atomic publication after all derived state succeeds.

- [ ] **Step 1: Prove whether hot reconfiguration mutates the published config**

Run:

```bash
rg -n '_applyHotFields|runtimeCfg|Reconfigure|UpdateConfig|atomic' go/runtime.go go/runtime_facade.go go/logger.go go/multi_handler.go
(cd go && go test ./... -run 'Reconfig|HotReload' -count=20)
```

Expected: `_applyHotFields(_runtimeCfg, target)` writes through the currently published pointer, and existing tests do not assert that prior snapshots remain unchanged.

- [ ] **Step 2: Add failing immutability and concurrent-emission tests**

```go
func TestReconfigurePublishesNewGenerationWithoutMutatingOld(t *testing.T) {
	resetRuntimeForTest()
	Setup(TelemetryConfig{ServiceName: "svc", LogLevel: "info"})
	old := loadRuntimeGeneration()
	if err := Reconfigure(TelemetryConfig{ServiceName: "svc", LogLevel: "debug"}); err != nil {
		t.Fatal(err)
	}
	current := loadRuntimeGeneration()
	if old.number == current.number || old.config.LogLevel != "info" || current.config.LogLevel != "debug" {
		t.Fatalf("old=%+v current=%+v", old, current)
	}
}

func TestConcurrentLoggingAndReconfigureUsesWholeGenerations(t *testing.T) {
	resetRuntimeForTest()
	Setup(TelemetryConfig{ServiceName: "svc", LogLevel: "info"})
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(2)
		go func() { defer wg.Done(); GetLogger("race").Info("event") }()
		go func(i int) {
			defer wg.Done()
			level := "info"
			if i%2 == 0 { level = "debug" }
			if err := Reconfigure(TelemetryConfig{ServiceName: "svc", LogLevel: level}); err != nil { t.Error(err) }
		}(i)
	}
	wg.Wait()
}
```

- [ ] **Step 3: Run under the race detector and verify red**

Run:

```bash
(cd go && go test -race ./... -run 'TestReconfigurePublishesNewGenerationWithoutMutatingOld|TestConcurrentLoggingAndReconfigureUsesWholeGenerations' -count=10)
```

Expected: the immutability assertion fails; the race detector may also identify a config or handler race.

- [ ] **Step 4: Build and atomically publish complete generations**

```go
type runtimeGeneration struct {
	number uint64
	config *TelemetryConfig
	logger *slog.Logger
}

var activeGeneration atomic.Pointer[runtimeGeneration]

func loadRuntimeGeneration() runtimeGeneration {
	current := activeGeneration.Load()
	if current == nil { return runtimeGeneration{} }
	return runtimeGeneration{
		number: current.number,
		config: cloneTelemetryConfig(current.config),
		logger: current.logger,
	}
}

func publishRuntimeGeneration(config *TelemetryConfig, logger *slog.Logger, number uint64) {
	activeGeneration.Store(&runtimeGeneration{
		number: number,
		config: cloneTelemetryConfig(config),
		logger: logger,
	})
}
```

Under the existing setup mutex, clone and validate the target, apply policies to the clone, construct the logger from copied values, then publish once. Delete `_applyHotFields` and make handlers retain no `*TelemetryConfig`. Keep provider adoption and ownership mutations under the setup mutex.

- [ ] **Step 5: Run focused and full Go race gates**

Run:

```bash
(cd go && go test -race ./... -run 'Reconfig|HotReload|ConcurrentLogging|Generation' -count=20)
(cd go && go test -race ./...)
(cd go/otel && go test -race ./...)
```

Expected: all tests pass with no data race and old generation copies stay unchanged.

- [ ] **Step 6: Commit immutable Go generations**

```bash
git add go/runtime_generation.go go/runtime.go go/runtime_facade.go go/setup.go go/logger.go go/multi_handler.go go/health.go go/*generation_test.go go/runtime_reconfigure_test.go go/runtime_reconfigure_logging_test.go go/runtime_hotreload_test.go
git commit -m "fix(go): publish immutable runtime generations"
```

### Task 6: Harden typed Go containers and deliver canonical receipts

**Files:**
- Modify: `go/internal/piicore/pii.go`
- Modify: `go/pii.go`
- Modify: `go/receipts.go`
- Modify: `go/health.go`
- Modify: `go/telemetry.go`
- Modify: `go/logger.go`
- Modify: `go/otel/exporters.go`
- Create: `go/receipt_fixtures_test.go`
- Modify: `go/pii_test.go`
- Modify: `go/receipts_test.go`
- Modify: `go/parity_health_test.go`
- Modify: `go/runtime_gates_test.go`

**Interfaces:**
- Consumes: the Task 2 vectors and Task 5 immutable config generations.
- Produces: `type ReceiptSink interface { Emit(RedactionReceipt) bool }`; `TestReceiptCollector` capped at 1,024; reflective `Harden(value any, limits Limits) any`; canonical `ReceiptFailures uint64` health field.

- [ ] **Step 1: Confirm traversal stops at typed containers**

Run:

```bash
rg -n 'map\[string\](any|interface)|\[\](any|interface)|reflect\.|ReceiptSink|ReceiptFailures' go/internal/piicore go/pii.go go/receipts.go go/health.go
```

Expected: traversal handles only `map[string]any` and `[]any`; no receipt sink or receipt-failure counter exists.

- [ ] **Step 2: Add failing typed-container, cycle, vector, and sink tests**

```go
type credentials struct {
	Password string `json:"password"`
	Public   string `json:"public"`
}

func TestHardenTraversesTypedContainersAndCycles(t *testing.T) {
	cycle := map[string]any{}
	cycle["self"] = cycle
	input := map[string]any{
		"rows": []credentials{{Password: "secret", Public: "ok"}},
		"cycle": cycle,
	}
	got := Harden(input, DefaultLimits())
	want := map[string]any{
		"rows": []any{map[string]any{"password": "***", "public": "ok"}},
		"cycle": map[string]any{"self": "***"},
	}
	if diff := cmp.Diff(want, got); diff != "" { t.Fatal(diff) }
}

type rejectingSink struct{}
func (rejectingSink) Emit(RedactionReceipt) bool { return false }

func TestReceiptSinkRejectionIncrementsHealth(t *testing.T) {
	resetHealthForTest()
	emitReceipt(testReceipt(t), rejectingSink{})
	if got := Health().ReceiptFailures; got != 1 { t.Fatalf("got %d", got) }
}

func TestSignalPipelineMatchesCanonicalCases(t *testing.T) {
	for _, tc := range loadPipelineCases(t) {
		observer := &recordingPipelineObserver{}
		processSignal(tc.Input, observer)
		if diff := cmp.Diff(tc.Expected, observer.Events); diff != "" { t.Errorf("%s: %s", tc.ID, diff) }
	}
}
```

Load every YAML vector in `receipt_fixtures_test.go` and assert its canonical JSON, original hash, payload, and signature.

- [ ] **Step 3: Run focused tests to verify red**

Run:

```bash
(cd go && go test ./... -run 'HardenTraversesTypedContainersAndCycles|ReceiptFixture|ReceiptSinkRejection|Health' -count=1)
```

Expected: typed structs and cycles pass through incorrectly, vector signing or timestamp formatting differs, and the health field is missing.

- [ ] **Step 4: Implement reflective normalization with cycle protection**

```go
type visit struct {
	typ reflect.Type
	ptr uintptr
}

func hardenValue(value reflect.Value, seen map[visit]struct{}, depth int, limits Limits) any {
	for value.IsValid() && (value.Kind() == reflect.Interface || value.Kind() == reflect.Pointer) {
		if value.IsNil() { return nil }
		value = value.Elem()
	}
	if !value.IsValid() { return nil }
	if depth > limits.MaxDepth { return "***" }
	if identity, ok := referenceIdentity(value); ok {
		if _, exists := seen[identity]; exists { return "***" }
		seen[identity] = struct{}{}
		defer delete(seen, identity)
	}
	return hardenKind(value, seen, depth, limits)
}
```

For maps, require string keys; for structs, traverse exported fields using JSON names; for arrays and slices, preserve order; unsupported composites become `"***"`; scalars use invariant formatting before limits and secret detection. Implement RFC 8785 serialization and real `crypto/hmac` signing in `receipts.go`. Require a sink in production when receipts are enabled, cap only `TestReceiptCollector`, count sink rejection/panic, and never call the logger from that error path. Apply hardening before local and OTel handlers.

Call the sink through this panic boundary:

```go
func callReceiptSink(sink ReceiptSink, receipt RedactionReceipt) (accepted bool) {
	defer func() {
		if recover() != nil { accepted = false }
	}()
	return sink.Emit(receipt)
}
```

- [ ] **Step 5: Run Go governance and race gates**

Run:

```bash
(cd go && go test -race ./... -run 'Harden|PII|Receipt|Health|RuntimeGates')
(cd go && go test -race ./...)
(cd go/otel && go test -race ./...)
```

Expected: all vector and traversal cases pass; race detector is clean.

- [ ] **Step 6: Commit Go governance parity**

```bash
git add go/internal/piicore/pii.go go/pii.go go/receipts.go go/health.go go/telemetry.go go/logger.go go/otel/exporters.go go/receipt_fixtures_test.go go/pii_test.go go/receipts_test.go go/parity_health_test.go go/runtime_gates_test.go
git commit -m "feat(go): harden typed values and deliver receipts"
```

### Task 7: Serialize Python lifecycle operations around immutable generations

**Files:**
- Create: `src/provide/telemetry/_lifecycle.py`
- Modify: `src/provide/telemetry/setup.py`
- Modify: `src/provide/telemetry/runtime.py`
- Modify: `src/provide/telemetry/_runtime_types.py`
- Modify: `src/provide/telemetry/_provider_drain.py`
- Create: `tests/concurrency/test_lifecycle_interleavings.py`
- Modify: `tests/setup/test_setup_lifecycle.py`
- Modify: `tests/runtime/test_reconfigure_telemetry_messages.py`
- Modify: `tests/integration/test_setup_reinitialization.py`

**Interfaces:**
- Consumes: `TelemetryConfig`, policy application, logger configuration, and owned provider references.
- Produces: `LifecycleGeneration(number: int, config: TelemetryConfig, setup_done: bool)`; one `LifecycleCoordinator` for setup, update, reconfigure, flush, and shutdown; disposal tickets detached under the lock and drained outside it.

- [ ] **Step 1: Characterize the current split-lock and repeated-setup behavior**

Run:

```bash
rg -n '_lock|_reconfigure_lock|setup_telemetry|apply_runtime_config|shutdown' src/provide/telemetry/setup.py src/provide/telemetry/runtime.py
uv run pytest tests/setup/test_setup_lifecycle.py tests/integration/test_setup_reinitialization.py -q
```

Expected: setup and runtime own separate locks, `setup_telemetry` parses the caller's new config before detecting prior setup, and `apply_runtime_config` publishes before all policy application completes.

- [ ] **Step 2: Add failing truthfulness and deterministic interleaving tests**

```python
def test_repeated_setup_returns_active_copy_without_parsing_new_input(monkeypatch):
    active = setup_telemetry(TelemetryConfig(service_name="active"))
    monkeypatch.setenv("PROVIDE_TELEMETRY_TRACES_SAMPLE_RATE", "invalid")
    repeated = setup_telemetry(TelemetryConfig(service_name="ignored"))
    assert repeated == active
    assert repeated is not active


def test_reconfigure_does_not_publish_before_policies_finish(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def blocked_apply(config):
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(runtime, "_apply_policies", blocked_apply)
    worker = threading.Thread(target=lambda: reconfigure_telemetry(log_level="debug"))
    worker.start()
    assert entered.wait(2)
    assert runtime_status().config.log_level == "info"
    release.set()
    worker.join(2)
    assert runtime_status().config.log_level == "debug"
```

Add a shutdown test whose fake provider blocks in `shutdown()` and assert a concurrent read of `runtime_status()` completes while provider disposal remains blocked.

- [ ] **Step 3: Run the lifecycle tests and verify red**

Run:

```bash
uv run pytest tests/concurrency/test_lifecycle_interleavings.py tests/setup/test_setup_lifecycle.py tests/integration/test_setup_reinitialization.py -q
```

Expected: invalid environment is parsed on repeated setup, a partial generation becomes visible, or provider disposal holds the lifecycle lock.

- [ ] **Step 4: Implement one coordinator and publish only complete generations**

```python
@dataclass(frozen=True, slots=True)
class LifecycleGeneration:
    number: int
    config: TelemetryConfig
    setup_done: bool


class LifecycleCoordinator:
    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._generation = LifecycleGeneration(0, TelemetryConfig(), False)

    def snapshot(self) -> LifecycleGeneration:
        with self._condition:
            return copy.deepcopy(self._generation)

    def publish(self, config: TelemetryConfig, *, setup_done: bool) -> LifecycleGeneration:
        self._generation = LifecycleGeneration(
            self._generation.number + 1, copy.deepcopy(config), setup_done
        )
        self._condition.notify_all()
        return copy.deepcopy(self._generation)
```

Route setup, update, reconfigure, flush, and shutdown through one module-level coordinator. On repeated setup, check `setup_done` before parsing arguments or environment and return `snapshot().config`. Build and validate the candidate, apply policies and logging, then publish. During shutdown, detach owned providers and publish the stopped generation under the coordinator lock, then perform concurrent bounded drains and disposal after leaving the lock.

- [ ] **Step 5: Run lifecycle, concurrency, and full Python tests**

Run:

```bash
uv run pytest tests/concurrency/test_lifecycle_interleavings.py tests/setup tests/runtime tests/integration/test_setup_reinitialization.py -q
uv run pytest -q
uv run mypy src
uv run ruff check src tests
```

Expected: all commands pass, repeated setup ignores unapplied inputs, and no test observes a partial generation.

- [ ] **Step 6: Commit the Python lifecycle coordinator**

```bash
git add src/provide/telemetry/_lifecycle.py src/provide/telemetry/setup.py src/provide/telemetry/runtime.py src/provide/telemetry/_runtime_types.py src/provide/telemetry/_provider_drain.py tests/concurrency/test_lifecycle_interleavings.py tests/setup/test_setup_lifecycle.py tests/runtime/test_reconfigure_telemetry_messages.py tests/integration/test_setup_reinitialization.py
git commit -m "fix(py): serialize lifecycle generation publication"
```

### Task 8: Implement canonical Python receipt delivery and health accounting

**Files:**
- Modify: `src/provide/telemetry/receipts.py`
- Modify: `src/provide/telemetry/pii.py`
- Modify: `src/provide/telemetry/health.py`
- Modify: `src/provide/telemetry/config.py`
- Modify: `src/provide/telemetry/logger/processors.py`
- Modify: `src/provide/telemetry/logger/handlers.py`
- Modify: `src/provide/telemetry/logger/_otel_logs.py`
- Create: `tests/governance/test_receipt_fixtures.py`
- Modify: `tests/governance/test_receipts.py`
- Modify: `tests/hardening/test_input_hardening.py`
- Modify: `tests/health/test_health_snapshot_mapping.py`
- Modify: `tests/governance/test_governance_integration.py`

**Interfaces:**
- Consumes: Task 2 vectors and Task 7 lifecycle config snapshots.
- Produces: `class ReceiptSink(Protocol): emit(self, receipt: RedactionReceipt) -> bool`; bounded `TestReceiptCollector`; `HealthSnapshot.receipt_failures`; hardening before every capture or export sink.

- [ ] **Step 1: Characterize receipt buffering and hardening order**

Run:

```bash
rg -n 'receipt|collector|buffer|hmac|hard(en|ening)|process' src/provide/telemetry/receipts.py src/provide/telemetry/pii.py src/provide/telemetry/logger tests/governance
```

Expected: production delivery logs or summarizes receipts instead of requiring a synchronous sink, and no global receipt-failure health counter exists.

- [ ] **Step 2: Add failing fixture, sink-failure, and pre-capture tests**

```python
@pytest.mark.parametrize("vector", load_receipt_vectors(), ids=lambda row: row["id"])
def test_receipt_vectors(vector):
    receipt = sign_receipt(
        vector["input"],
        key=vector["key"].encode(),
        receipt_id=vector["receipt_id"],
        timestamp=vector["timestamp"],
        field_path=vector["field_path"],
        action=vector["action"],
    )
    assert receipt.original_hash == vector["original_hash"]
    assert receipt.signature == vector["signature"]


def test_receipt_sink_exception_counts_failure_without_logging(caplog):
    class BrokenSink:
        def emit(self, receipt):
            raise RuntimeError("sink down")

    emit_receipt(make_receipt(), BrokenSink())
    assert health_snapshot().receipt_failures == 1
    assert not caplog.records


def test_cycle_is_masked_before_capture(captured_records):
    value = {}
    value["self"] = value
    get_logger("test").info("event", payload=value)
    assert captured_records[0]["payload"] == {"self": "***"}


@pytest.mark.parametrize("case", load_pipeline_cases(), ids=lambda row: row["id"])
def test_signal_pipeline_order(case):
    observer = RecordingPipelineObserver()
    process_signal(case["input"], observer=observer)
    assert observer.events == case["expected"]
```

- [ ] **Step 3: Run focused tests and verify red**

Run:

```bash
uv run pytest tests/governance/test_receipt_fixtures.py tests/governance/test_receipts.py tests/hardening/test_input_hardening.py tests/health/test_health_snapshot_mapping.py -q
```

Expected: canonical digest or delivery assertions fail, cycle capture is unsafe, and `receipt_failures` is absent.

- [ ] **Step 4: Implement canonical receipts and non-recursive failure accounting**

```python
class ReceiptSink(Protocol):
    def emit(self, receipt: RedactionReceipt, /) -> bool: ...


class TestReceiptCollector:
    def __init__(self) -> None:
        self.receipts: deque[RedactionReceipt] = deque(maxlen=1024)

    def emit(self, receipt: RedactionReceipt, /) -> bool:
        self.receipts.append(receipt)
        return True


def emit_receipt(receipt: RedactionReceipt, sink: ReceiptSink) -> None:
    try:
        accepted = sink.emit(receipt)
    except Exception:
        accepted = False
    if not accepted:
        increment_receipt_failures()
```

Serialize the normalized JSON model with RFC 8785 number/string/object rules, hash with `hashlib.sha256`, sign with `hmac.new(..., hashlib.sha256)`, and format timestamps as `%Y-%m-%dT%H:%M:%S.` plus three millisecond digits and `Z`. Validate that production receipt enablement includes a sink. Use an identity set during recursive hardening; cycles and uninspectable composites become `"***"`. Place hardening before capture buffers, renderers, receipt construction, and OTel handlers.

- [ ] **Step 5: Run Python governance and complete quality gates**

Run:

```bash
uv run pytest tests/governance tests/hardening tests/health tests/logger -q
uv run pytest -q
uv run coverage run -m pytest -q
uv run coverage report --fail-under=100
uv run mypy src
uv run ruff check src tests
```

Expected: all commands pass with 100% configured coverage and the test collector never exceeds 1,024 entries.

- [ ] **Step 6: Commit Python governance parity**

```bash
git add src/provide/telemetry/receipts.py src/provide/telemetry/pii.py src/provide/telemetry/health.py src/provide/telemetry/config.py src/provide/telemetry/logger tests/governance tests/hardening/test_input_hardening.py tests/health/test_health_snapshot_mapping.py
git commit -m "feat(py): deliver canonical governance receipts"
```

### Task 9: Make Rust configuration claims executable and prune baseline dependencies

**Files:**
- Modify: `rust/src/config/mod.rs`
- Modify: `rust/src/config/from_env.rs`
- Modify: `rust/src/config/validate.rs`
- Modify: `rust/src/runtime.rs`
- Modify: `rust/src/runtime_facade.rs`
- Modify: `rust/Cargo.toml`
- Modify: `rust/Cargo.lock`
- Create: `rust/tests/config_applicability.rs`
- Modify: `rust/src/runtime_tests.rs`
- Modify: `rust/examples/config_probe.rs`

**Interfaces:**
- Consumes: Task 1 `config_defaults[*].applicability`.
- Produces: an executable Rust config dump matching every schema entry whose applicability contains `rust`; baseline dependency graph with OTel-only crates reachable only through `otel` or `otel-grpc`.

- [ ] **Step 1: Compare actual Rust config and dependency use with the schema**

Run:

```bash
python spec/check_config_parity.py --language rust || true
rg -n 'include_caller|include_code|pretty|allow_blocking|error_taxonomy' rust/src rust/tests
(cd rust && cargo machete)
```

Expected: the config probe is absent or reports shared-field drift, and `cargo machete` identifies unused or unnecessarily unconditional dependencies. Preserve any dependency with a real baseline consumer even if its use is indirect.

- [ ] **Step 2: Add a failing executable config comparison**

```rust
#[test]
fn rust_config_probe_matches_applicable_contract_defaults() {
    let expected = contract::applicable_config_defaults("rust");
    let actual = provide_telemetry::testing::config_defaults_probe();
    assert_eq!(actual, expected);
}

#[test]
fn invalid_shared_config_is_rejected_without_clamping() {
    let mut config = TelemetryConfig::default();
    config.sampling.logs_rate = 1.01;
    assert!(matches!(config.validate(), Err(ConfigError::InvalidSamplingRate { .. })));
}
```

- [ ] **Step 3: Verify config and dependency gates are red**

Run:

```bash
(cd rust && cargo test --test config_applicability)
python spec/check_config_parity.py --language rust
```

Expected: missing shared fields or applicability mismatches fail the comparison.

- [ ] **Step 4: Implement only schema-applicable fields and feature boundaries**

Add fields with exact schema names and defaults to focused config structs; for example:

```rust
pub struct LoggingConfig {
    pub level: String,
    pub fmt: String,
    pub include_timestamp: bool,
    pub include_caller: bool,
    pub include_code_attributes: bool,
    pub pretty_colors: bool,
    pub fields: HashMap<String, serde_json::Value>,
    pub otlp_headers: HashMap<String, String>,
    pub otlp_endpoint: Option<String>,
    pub otlp_enabled: bool,
    pub otlp_protocol: String,
    pub module_levels: HashMap<String, String>,
}
```

Wire environment parsing, validation, runtime updates, and probe output for every applicable field. When the contract explicitly marks a field inapplicable to Rust, do not add a dead field. Move crates used only by OTel modules behind `otel`; remove dependencies proven unused by `cargo machete`, `cargo test --no-default-features`, and `cargo test --all-features` together.

- [ ] **Step 5: Run Rust baseline and feature matrices**

Run:

```bash
(cd rust && cargo fmt --check)
(cd rust && cargo clippy --no-default-features --all-targets -- -D warnings)
(cd rust && cargo test --no-default-features --all-targets)
(cd rust && cargo clippy --all-features --all-targets -- -D warnings)
(cd rust && cargo test --all-features --all-targets)
(cd rust && cargo machete)
python spec/check_config_parity.py --language rust
```

Expected: all commands pass and `cargo machete` reports no unused dependency.

- [ ] **Step 6: Commit Rust config and dependency parity**

```bash
git add rust/src/config rust/src/runtime.rs rust/src/runtime_facade.rs rust/Cargo.toml rust/Cargo.lock rust/tests/config_applicability.rs rust/examples/config_probe.rs
git commit -m "feat(rust): enforce applicable config contract"
```

### Task 10: Apply canonical Rust hardening and receipt delivery before sinks

**Files:**
- Modify: `rust/src/receipts.rs`
- Modify: `rust/src/pii.rs`
- Modify: `rust/src/health.rs`
- Modify: `rust/src/runtime.rs`
- Modify: `rust/src/setup.rs`
- Modify: `rust/src/lib.rs`
- Create: `rust/tests/receipt_fixtures.rs`
- Create: `rust/tests/signal_pipeline_order.rs`
- Modify: `rust/src/health_tests.rs`
- Modify: `rust/src/runtime_logging_tests.rs`

**Interfaces:**
- Consumes: Task 2 receipt vectors and Task 9 config applicability.
- Produces: `pub trait ReceiptSink: Send + Sync { fn emit(&self, receipt: &RedactionReceipt) -> bool; }`; `Arc<dyn ReceiptSink>` in active config; 1,024-entry test collector; `HealthSnapshot.receipt_failures`.

- [ ] **Step 1: Characterize timestamp, hashing, and sink behavior**

Run:

```bash
rg -n 'SystemTime|format!|hmac|Receipt|VecDeque|sink|serde_json::Value' rust/src/receipts.rs rust/src/pii.rs rust/src/runtime.rs
```

Expected: HMAC exists, but timestamp formatting is debug text, original values are stringified without JCS, and production delivery has no required sink.

- [ ] **Step 2: Add failing vectors and sink-accounting tests**

```rust
#[test]
fn receipt_vectors_match_exactly() {
    for vector in fixtures::receipt_cases() {
        let receipt = sign_receipt_at(
            &vector.input, &vector.key, &vector.receipt_id,
            &vector.timestamp, &vector.field_path, &vector.action,
        ).unwrap();
        assert_eq!(receipt.original_hash, vector.original_hash);
        assert_eq!(receipt.signature, vector.signature);
    }
}

struct RejectingSink;
impl ReceiptSink for RejectingSink {
    fn emit(&self, _: &RedactionReceipt) -> bool { false }
}

#[test]
fn sink_rejection_increments_global_health() {
    testing::reset_health();
    emit_receipt(&fixture_receipt(), &RejectingSink);
    assert_eq!(health_snapshot().receipt_failures, 1);
}
```

Add a runtime capture assertion proving nested arrays are redacted before both local capture and the fake OTel sink.

Add this fixture-driven pipeline assertion:

```rust
#[test]
fn every_signal_exit_matches_canonical_stage_order() {
    for case in fixtures::pipeline_cases() {
        let observer = RecordingPipelineObserver::default();
        process_signal(case.input, &observer);
        assert_eq!(observer.events(), case.expected);
    }
}
```

- [ ] **Step 3: Run focused Rust tests and verify red**

Run:

```bash
(cd rust && cargo test --test receipt_fixtures)
(cd rust && cargo test 'sink_rejection|hardening_precedes_sink|health')
```

Expected: timestamp, original hash, sink, and health assertions fail.

- [ ] **Step 4: Implement JCS, exact timestamps, sinks, and ordered hardening**

```rust
pub trait ReceiptSink: Send + Sync {
    fn emit(&self, receipt: &RedactionReceipt) -> bool;
}

pub fn emit_receipt(receipt: &RedactionReceipt, sink: &dyn ReceiptSink) {
    let accepted = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| sink.emit(receipt)))
        .unwrap_or(false);
    if !accepted { health::increment_receipt_failures(); }
}
```

Normalize to `serde_json::Value`, render RFC 8785 canonical JSON, compute SHA-256 and HMAC-SHA256, and format UTC milliseconds with `time = { version = "=0.3.36", features = ["formatting", "macros"] }`. Reject non-test receipt enablement without `Arc<dyn ReceiptSink>`. Cap the test collector at 1,024. Run hardening before local capture, receipt construction, and OTel bridges. Preserve existing RAII context restoration.

- [ ] **Step 5: Run all Rust gates without touching the user-modified test**

Run:

```bash
(cd rust && cargo fmt --check)
(cd rust && cargo clippy --all-features --all-targets -- -D warnings)
(cd rust && cargo test --all-features --all-targets)
git diff -- rust/src/resilience_state_tests.rs
```

Expected: Rust gates pass and the final diff for `rust/src/resilience_state_tests.rs` contains only the user's pre-existing change.

- [ ] **Step 6: Commit Rust governance parity without staging the user file**

```bash
git add rust/src/receipts.rs rust/src/pii.rs rust/src/health.rs rust/src/runtime.rs rust/src/setup.rs rust/src/lib.rs rust/tests/receipt_fixtures.rs rust/tests/signal_pipeline_order.rs rust/src/health_tests.rs rust/src/runtime_logging_tests.rs
git commit -m "feat(rust): canonicalize and deliver governance receipts"
```

### Task 11: Split C# into an OTel-free core and an integration package

**Files:**
- Create: `csharp/src/Provide.Telemetry/Backend.cs`
- Create: `csharp/src/Provide.Telemetry/CanonicalLogRecord.cs`
- Create: `csharp/src/Provide.Telemetry/LifecycleGeneration.cs`
- Create: `csharp/src/Provide.Telemetry.OpenTelemetry/Provide.Telemetry.OpenTelemetry.csproj`
- Create: `csharp/src/Provide.Telemetry.OpenTelemetry/OpenTelemetryBackendRegistration.cs`
- Move: `csharp/src/Provide.Telemetry/Otel/OtelBackend.cs` to `csharp/src/Provide.Telemetry.OpenTelemetry/OpenTelemetryBackend.cs`
- Move: `csharp/src/Provide.Telemetry/Otel/OtelInstruments.cs` to `csharp/src/Provide.Telemetry.OpenTelemetry/OtelInstruments.cs`
- Modify: `csharp/src/Provide.Telemetry/Provide.Telemetry.csproj`
- Modify: `csharp/Provide.Telemetry.sln`
- Delete: `csharp/Provide.Telemetry.slnx`
- Create: `csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/Provide.Telemetry.OpenTelemetry.Tests.csproj`
- Create: `csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/PackageBoundaryTests.cs`
- Create: `csharp/consumer/Provide.Telemetry.CoreConsumer/Provide.Telemetry.CoreConsumer.csproj`
- Create: `csharp/consumer/Provide.Telemetry.CoreConsumer/Program.cs`
- Create: `csharp/consumer/Provide.Telemetry.OpenTelemetryConsumer/Provide.Telemetry.OpenTelemetryConsumer.csproj`
- Create: `csharp/consumer/Provide.Telemetry.OpenTelemetryConsumer/Program.cs`

**Interfaces:**
- Consumes: existing C# facade and OTel backend behavior.
- Produces: `ITelemetryBackend`, `TelemetryBackendRegistry.Register(Func<TelemetryConfig, ITelemetryBackend>)`, `CanonicalLogRecord`, internal `LifecycleGeneration(long Number, TelemetryConfig Config, ITelemetryBackend? Backend, RuntimeState State)`, and `OpenTelemetryBackendRegistration.Register()`; a core package with zero OTel or Microsoft DI references.

- [ ] **Step 1: Prove the current package boundary is not real**

Run:

```bash
rg -n 'PackageReference|OpenTelemetry|Microsoft.Extensions' csharp/src/Provide.Telemetry
dotnet list csharp/src/Provide.Telemetry/Provide.Telemetry.csproj package --include-transitive
```

Expected: the only package contains direct OTel, Microsoft DI, and Microsoft Logging references.

- [ ] **Step 2: Add failing package-boundary and consumer tests**

```csharp
[Fact]
public void CoreAssemblyHasNoOpenTelemetryOrMicrosoftDependencyInjectionReferences()
{
    var references = typeof(Telemetry).Assembly.GetReferencedAssemblies()
        .Select(name => name.Name).ToHashSet(StringComparer.Ordinal);
    Assert.DoesNotContain(references, name => name!.StartsWith("OpenTelemetry", StringComparison.Ordinal));
    Assert.DoesNotContain("Microsoft.Extensions.DependencyInjection", references);
}

[Fact]
public void IntegrationRegistersBackendWithoutCoreReferencingIntegration()
{
    OpenTelemetryBackendRegistration.Register();
    Assert.NotNull(TelemetryBackendRegistry.Create(TelemetryConfig.Default()));
}
```

Core consumer `Program.cs` calls `Telemetry.Setup`, logs, traces, records a metric, flushes, and shuts down without referencing the integration namespace. The integration consumer first calls `OpenTelemetryBackendRegistration.Register()` and then exercises the same facade.

- [ ] **Step 3: Verify the split tests fail**

Run:

```bash
dotnet test csharp/Provide.Telemetry.sln --filter 'PackageBoundary|IntegrationRegisters'
dotnet build csharp/consumer/Provide.Telemetry.CoreConsumer/Provide.Telemetry.CoreConsumer.csproj
```

Expected: new projects or interfaces are absent and the existing core assembly reference test fails.

- [ ] **Step 4: Introduce the backend boundary and move all OTel code**

```csharp
public interface ITelemetryBackend : IDisposable
{
    ProviderFlags Providers { get; }
    ITracer? GetTracer(string name);
    IMeter? GetMeter(string name);
    void EmitLog(CanonicalLogRecord record);
    FlushResult Flush(DateTimeOffset deadline);
    void Shutdown(DateTimeOffset deadline);
}

public static class TelemetryBackendRegistry
{
    private static Func<TelemetryConfig, ITelemetryBackend>? _factory;
    public static void Register(Func<TelemetryConfig, ITelemetryBackend> factory) =>
        Volatile.Write(ref _factory, factory ?? throw new ArgumentNullException(nameof(factory)));
    internal static ITelemetryBackend? Create(TelemetryConfig config) =>
        Volatile.Read(ref _factory)?.Invoke(config);
}

internal sealed record LifecycleGeneration(
    long Number,
    TelemetryConfig Config,
    ITelemetryBackend? Backend,
    RuntimeState State);
```

Core project references only BCL assemblies. Integration references core plus OTel packages. Update setup, logger, tracing, and metrics to call `ITelemetryBackend`; do not reflectively load integration. Add both package and test projects to the solution.

- [ ] **Step 5: Verify both dependency graphs and consumers**

Run:

```bash
dotnet restore csharp/Provide.Telemetry.sln
dotnet build csharp/Provide.Telemetry.sln --no-restore -warnaserror
dotnet test csharp/Provide.Telemetry.sln --no-build
dotnet list csharp/src/Provide.Telemetry/Provide.Telemetry.csproj package --include-transitive
dotnet build csharp/consumer/Provide.Telemetry.CoreConsumer/Provide.Telemetry.CoreConsumer.csproj
dotnet build csharp/consumer/Provide.Telemetry.OpenTelemetryConsumer/Provide.Telemetry.OpenTelemetryConsumer.csproj
```

Expected: core dependency output contains no OTel or Microsoft DI package; both consumers build.

- [ ] **Step 6: Commit the C# package split**

```bash
git add csharp
git commit -m "refactor(csharp): split core and OpenTelemetry packages"
```

### Task 12: Enforce canonical C# config, environment, resources, and local records

**Files:**
- Modify: `csharp/src/Provide.Telemetry/Config.cs`
- Modify: `csharp/src/Provide.Telemetry/ConfigEnv.cs`
- Modify: `csharp/src/Provide.Telemetry/Schema.cs`
- Modify: `csharp/src/Provide.Telemetry/Logger.cs`
- Modify: `csharp/src/Provide.Telemetry/Errors.cs`
- Modify: `csharp/src/Provide.Telemetry/Setup.cs`
- Modify: `csharp/src/Provide.Telemetry.OpenTelemetry/OpenTelemetryBackend.cs`
- Modify: `csharp/probes/ContractProbe/Program.cs`
- Modify: `csharp/probes/EmitLog/Program.cs`
- Create: `csharp/tests/Provide.Telemetry.Tests/CanonicalConfigTests.cs`
- Create: `csharp/tests/Provide.Telemetry.Tests/CanonicalLogRecordTests.cs`

**Interfaces:**
- Consumes: Task 1 schema applicability and Task 11 `CanonicalLogRecord`/backend interface.
- Produces: exact canonical environment vocabulary, percent-decoded OTLP headers with literal `+`, schema defaults of zero retries/backoff, canonical snake_case records, and canonical error fingerprints.

- [ ] **Step 1: Characterize aliases and wire drift**

Run:

```bash
rg -n 'PROVIDE_TELEMETRY_ENVIRONMENT|PROVIDE_LOG_OTLP|_MAX_SIZE|ENABLE_RED|USE|service\.name|trace\.id|Retries = 3|BackoffSeconds = 0\.5' csharp/src
```

Expected: legacy aliases, noncanonical names, dotted local fields, and retry defaults differ from the schema.

- [ ] **Step 2: Add failing config and canonical-record tests**

```csharp
[Fact]
public void LegacyEnvironmentNamesAreIgnored()
{
    using var env = new TestEnvironment("PROVIDE_TELEMETRY_ENVIRONMENT", "legacy");
    Assert.NotEqual("legacy", TelemetryConfig.FromEnvironment().Environment);
}

[Fact]
public void OtlpHeadersPercentDecodeWithoutConvertingPlusToSpace()
{
    using var env = new TestEnvironment("OTEL_EXPORTER_OTLP_HEADERS", "x=a%2Bb,y=c+d");
    Assert.Equal("a+b", TelemetryConfig.FromEnvironment().OtlpHeaders["x"]);
    Assert.Equal("c+d", TelemetryConfig.FromEnvironment().OtlpHeaders["y"]);
}

[Fact]
public void LocalErrorRecordUsesCanonicalSnakeCaseEnvelope()
{
    var record = Capture.Error(new InvalidOperationException("boom"));
    Assert.Contains("service_name", record.Attributes.Keys);
    Assert.Contains("trace_id", record.Attributes.Keys);
    Assert.Contains("error_fingerprint", record.Attributes.Keys);
    Assert.DoesNotContain("service.name", record.Attributes.Keys);
    Assert.DoesNotContain("trace.id", record.Attributes.Keys);
}

[Fact]
public void ExplicitResourceAttributesOverrideEnvironmentAndDetectedValues()
{
    using var env = new TestEnvironment("OTEL_SERVICE_NAME", "environment-service");
    var config = TelemetryConfig.Default();
    config.ServiceName = "explicit-service";
    config.ResourceAttributes = new Dictionary<string, string> {
        ["deployment.environment.name"] = "prod"
    };
    var resource = ResourceBuilder.Build(config, detected: new() { ["service.name"] = "detected-service" });
    Assert.Equal("explicit-service", resource["service.name"]);
    Assert.Equal("prod", resource["deployment.environment.name"]);
}
```

- [ ] **Step 3: Verify C# config/log tests fail**

Run:

```bash
dotnet test csharp/tests/Provide.Telemetry.Tests/Provide.Telemetry.Tests.csproj --filter 'CanonicalConfig|CanonicalLogRecord'
python spec/check_config_parity.py --language csharp
```

Expected: alias, header, default, envelope, or fingerprint assertions fail.

- [ ] **Step 4: Implement exact schema parsing and canonical records**

Parse only names listed for C# in `telemetry-api.yaml`; delete alias branches. Decode each `%HH` sequence but leave literal `+` unchanged. Validate sample rates in `[0,1]`, nonnegative sizes/retries/timeouts, and allowed endpoint schemes without clamping. Merge resources in detected, environment, then explicit order. Build `CanonicalLogRecord` once in core:

```csharp
public sealed record CanonicalLogRecord(
    DateTimeOffset Timestamp,
    string Level,
    string Event,
    string ServiceName,
    string? Environment,
    string? TraceId,
    string? SpanId,
    string? ErrorFingerprint,
    IReadOnlyDictionary<string, object?> Attributes);
```

Local renderers and OTel bridges consume that record; neither renames core fields. Compute error fingerprint from normalized exception type, message, and stack frames using the shared schema algorithm.

- [ ] **Step 5: Run C# conformance and probes**

Run:

```bash
dotnet test csharp/Provide.Telemetry.sln --filter 'Config|Environment|Log|Schema|Fingerprint'
dotnet run --project csharp/probes/ContractProbe/ContractProbe.csproj
dotnet run --project csharp/probes/EmitLog/EmitLog.csproj
python spec/check_config_parity.py --language csharp
python spec/run_behavioral_parity.py --lang csharp --strict
```

Expected: all pass and emitted records contain canonical snake_case keys only.

- [ ] **Step 6: Commit C# wire parity**

```bash
git add csharp/src csharp/probes csharp/tests/Provide.Telemetry.Tests/CanonicalConfigTests.cs csharp/tests/Provide.Telemetry.Tests/CanonicalLogRecordTests.cs
git commit -m "feat(csharp): enforce canonical config and records"
```

### Task 13: Implement recursive C# governance and canonical receipt sinks

**Files:**
- Modify: `csharp/src/Provide.Telemetry/Pii.cs`
- Modify: `csharp/src/Provide.Telemetry/Governance.cs`
- Modify: `csharp/src/Provide.Telemetry/Health.cs`
- Modify: `csharp/src/Provide.Telemetry/Config.cs`
- Modify: `csharp/src/Provide.Telemetry/Logger.cs`
- Modify: `csharp/src/Provide.Telemetry/Signals.cs`
- Modify: `csharp/src/Provide.Telemetry.OpenTelemetry/OpenTelemetryBackend.cs`
- Create: `csharp/tests/Provide.Telemetry.Tests/RecursiveHardeningTests.cs`
- Create: `csharp/tests/Provide.Telemetry.Tests/ReceiptFixtureTests.cs`
- Create: `csharp/tests/Provide.Telemetry.Tests/ReceiptSinkTests.cs`

**Interfaces:**
- Consumes: Task 2 vectors and Task 12 canonical records.
- Produces: `public interface IReceiptSink { bool Emit(RedactionReceipt receipt); }`; `TestReceiptCollector` capped at 1,024; reflection-based JSON-model normalization; `HealthSnapshot.ReceiptFailures`.

- [ ] **Step 1: Confirm list, JSON, POCO, and cycle gaps**

Run:

```bash
rg -n 'IDictionary|IEnumerable|JsonElement|JsonNode|PropertyInfo|FieldInfo|ReferenceEquality|Receipt|List<' csharp/src/Provide.Telemetry/Pii.cs csharp/src/Provide.Telemetry/Governance.cs
```

Expected: traversal is dictionary-specific, receipt storage is unbounded or disconnected, and no production sink contract exists.

- [ ] **Step 2: Add failing traversal, vector, cap, and failure tests**

```csharp
private sealed class SecretPoco { public string Password { get; init; } = "secret"; public string Public = "ok"; }

[Fact]
public void HardeningTraversesListsJsonPocosAndCycles()
{
    var cycle = new Dictionary<string, object?>(); cycle["self"] = cycle;
    var input = new object[] { new SecretPoco(), JsonNode.Parse("{\"token\":\"secret\"}"), cycle };
    Assert.Equal("***", ((IDictionary<string, object?>)((object[])Pii.Harden(input))[2])["self"]);
    Assert.DoesNotContain("secret", JsonSerializer.Serialize(Pii.Harden(input)));
}

[Theory]
[MemberData(nameof(ReceiptVectors.All), MemberType = typeof(ReceiptVectors))]
public void ReceiptMatchesVector(ReceiptVector vector)
{
    var receipt = Receipts.SignAt(vector.Input, vector.Key, vector.ReceiptId,
        vector.Timestamp, vector.FieldPath, vector.Action);
    Assert.Equal(vector.OriginalHash, receipt.OriginalHash);
    Assert.Equal(vector.Signature, receipt.Signature);
}

[Fact]
public void RejectingSinkCountsFailureWithoutLogging()
{
    TestState.Reset(); Receipts.Emit(TestData.Receipt, new RejectingSink());
    Assert.Equal(1UL, Health.Snapshot().ReceiptFailures);
    Assert.Empty(TestState.CapturedLogs);
}
```

- [ ] **Step 3: Verify governance tests fail**

Run:

```bash
dotnet test csharp/tests/Provide.Telemetry.Tests/Provide.Telemetry.Tests.csproj --filter 'RecursiveHardening|Receipt'
```

Expected: typed collections or POCO secrets leak, canonical vectors differ, and sink failure accounting is absent.

- [ ] **Step 4: Implement safe traversal and receipts**

```csharp
public interface IReceiptSink { bool Emit(RedactionReceipt receipt); }

internal static object? Normalize(object? value, HashSet<object> seen, int depth, HardeningLimits limits)
{
    if (value is null) return null;
    if (depth > limits.MaxDepth) return "***";
    if (IsComposite(value) && !seen.Add(value)) return "***";
    try { return NormalizeInspectableValue(value, seen, depth, limits); }
    catch (Exception error) when (error is NotSupportedException or TargetInvocationException) { return "***"; }
    finally { if (IsComposite(value)) seen.Remove(value); }
}
```

Traverse dictionaries with string keys, arrays, `IList`, `JsonElement`, `JsonNode`, and public readable POCO properties/fields. Unwrap nullable values. Sort object keys lexicographically by UTF-16 code units for JCS, use invariant binary64 formatting, exact UTC milliseconds, SHA-256, and `HMACSHA256`. Validate enabled production receipts have a sink. Catch sink rejection/exception, increment `ReceiptFailures`, and do not log. Harden before capture, receipt, renderer, or backend receives data.

- [ ] **Step 5: Run C# governance suite**

Run:

```bash
dotnet test csharp/Provide.Telemetry.sln --filter 'Pii|Governance|Receipt|Hardening|Health'
```

Expected: vectors, cycles, JSON, lists, POCOs, 1,024 cap, and failure accounting all pass.

- [ ] **Step 6: Commit C# governance parity**

```bash
git add csharp/src csharp/tests/Provide.Telemetry.Tests/RecursiveHardeningTests.cs csharp/tests/Provide.Telemetry.Tests/ReceiptFixtureTests.cs csharp/tests/Provide.Telemetry.Tests/ReceiptSinkTests.cs
git commit -m "feat(csharp): enforce recursive governance parity"
```

### Task 14: Restore C# scoped context and make metrics and signal order race-free

**Files:**
- Modify: `csharp/src/Provide.Telemetry/Context.cs`
- Modify: `csharp/src/Provide.Telemetry/Tracing.cs`
- Modify: `csharp/src/Provide.Telemetry/Metrics.cs`
- Modify: `csharp/src/Provide.Telemetry/Signals.cs`
- Modify: `csharp/src/Provide.Telemetry/Backpressure.cs`
- Modify: `csharp/src/Provide.Telemetry/Health.cs`
- Modify: `csharp/src/Provide.Telemetry.OpenTelemetry/OtelInstruments.cs`
- Modify: `csharp/src/Provide.Telemetry.OpenTelemetry/OpenTelemetryBackend.cs`
- Create: `csharp/tests/Provide.Telemetry.Tests/ScopedContextTests.cs`
- Create: `csharp/tests/Provide.Telemetry.Tests/SignalPipelineOrderTests.cs`
- Create: `csharp/tests/Provide.Telemetry.Tests/ConcurrentMetricsTests.cs`

**Interfaces:**
- Consumes: Task 11 backend interfaces and Task 13 pre-sink hardening.
- Produces: predecessor-restoring `IDisposable` context/span scopes; atomic gauge and histogram state; one ordered `SignalPipeline.Process` path with exactly-once ticket release and canonical health transitions.

- [ ] **Step 1: Characterize context disposal and metric synchronization**

Run:

```bash
rg -n 'AsyncLocal|Dispose|Interlocked|lock|double|Histogram|Gauge|Release' csharp/src/Provide.Telemetry/Context.cs csharp/src/Provide.Telemetry/Tracing.cs csharp/src/Provide.Telemetry/Metrics.cs csharp/src/Provide.Telemetry.OpenTelemetry/OtelInstruments.cs csharp/src/Provide.Telemetry/Signals.cs
```

Expected: span disposal does not restore the predecessor and at least one gauge or histogram sum uses unsynchronized `double` state.

- [ ] **Step 2: Add failing nested, concurrency, and pipeline-order tests**

```csharp
[Fact]
public async Task NestedSpanRestoresPredecessorExactlyOnceAcrossAwait()
{
    using var outer = Tracing.StartSpan("outer"); var outerId = Context.Current.TraceId;
    await Task.Yield();
    var inner = Tracing.StartSpan("inner"); Assert.NotEqual(outerId, Context.Current.TraceId);
    inner.Dispose(); inner.Dispose();
    Assert.Equal(outerId, Context.Current.TraceId);
}

[Fact]
public void ConcurrentHistogramRecordsHaveExactCountAndSum()
{
    var histogram = Metrics.CreateHistogram("parallel");
    Parallel.For(0, 10_000, _ => histogram.Record(1));
    Assert.Equal(10_000UL, histogram.Snapshot.Count);
    Assert.Equal(10_000d, histogram.Snapshot.Sum);
}

[Fact]
public void PipelineUsesCanonicalOrderAndReleasesTicketOnce()
{
    var observer = new RecordingPipelineObserver();
    SignalPipeline.Process(TestData.Signal, observer);
    Assert.Equal(new[] { "consent", "sampling", "backpressure", "hardening", "pii",
        "receipt", "local", "backend", "health", "release" }, observer.Events);
    Assert.Equal(1, observer.ReleaseCount);
}
```

- [ ] **Step 3: Run the C# concurrency tests and verify red**

Run:

```bash
dotnet test csharp/tests/Provide.Telemetry.Tests/Provide.Telemetry.Tests.csproj --filter 'ScopedContext|ConcurrentMetrics|SignalPipelineOrder' -- RunConfiguration.MaxCpuCount=8
```

Expected: predecessor, exact sum/count, order, or release-count assertions fail.

- [ ] **Step 4: Implement scoped restoration, atomic numeric state, and one pipeline**

```csharp
internal sealed class ContextScope<T>(AsyncLocal<T?> slot, T? predecessor) : IDisposable
{
    private int _disposed;
    public void Dispose()
    {
        if (Interlocked.Exchange(ref _disposed, 1) == 0) slot.Value = predecessor;
    }
}

internal sealed class AtomicDouble
{
    private long _bits;
    public double Read() => BitConverter.Int64BitsToDouble(Volatile.Read(ref _bits));
    public void Add(double value)
    {
        long before, after;
        do {
            before = Volatile.Read(ref _bits);
            after = BitConverter.DoubleToInt64Bits(BitConverter.Int64BitsToDouble(before) + value);
        } while (Interlocked.CompareExchange(ref _bits, after, before) != before);
    }
}
```

Capture the predecessor before each `AsyncLocal` write and share the idempotent scope pattern between context and spans. Use `Interlocked` for counts and `AtomicDouble` for gauge/sum state in core and OTel instruments. Centralize signal exits in `try/finally` so an acquired ticket releases once. Record dropped/emitted/failures/retries/latency/breaker health at the canonical stage.

- [ ] **Step 5: Stress the C# context, metric, and pipeline suites**

Run:

```bash
for i in $(seq 1 20); do dotnet test csharp/Provide.Telemetry.sln --filter 'ScopedContext|ConcurrentMetrics|SignalPipelineOrder' --no-restore || exit 1; done
dotnet test csharp/Provide.Telemetry.sln --filter 'Tracing|Context|Metrics|Signals|Backpressure|Health'
```

Expected: every iteration passes with exact snapshots and correct restoration.

- [ ] **Step 6: Commit C# context and signal correctness**

```bash
git add csharp/src csharp/tests/Provide.Telemetry.Tests/ScopedContextTests.cs csharp/tests/Provide.Telemetry.Tests/SignalPipelineOrderTests.cs csharp/tests/Provide.Telemetry.Tests/ConcurrentMetricsTests.cs
git commit -m "fix(csharp): restore context and serialize signal state"
```

### Task 15: Connect C# resilience to exporters and enforce absolute lifecycle deadlines

**Files:**
- Modify: `csharp/src/Provide.Telemetry/Resilience.cs`
- Modify: `csharp/src/Provide.Telemetry/Setup.cs`
- Modify: `csharp/src/Provide.Telemetry/RuntimeFacade.cs`
- Modify: `csharp/src/Provide.Telemetry/Health.cs`
- Modify: `csharp/src/Provide.Telemetry.OpenTelemetry/OpenTelemetryBackend.cs`
- Create: `csharp/src/Provide.Telemetry.OpenTelemetry/ResilientExporter.cs`
- Create: `csharp/src/Provide.Telemetry.OpenTelemetry/ProviderDrain.cs`
- Create: `csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/ResilientExporterTests.cs`
- Create: `csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/ProviderDeadlineTests.cs`
- Create: `csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/ProcessEnvironmentTests.cs`

**Interfaces:**
- Consumes: Task 11 backend boundary and Task 14 canonical health updates.
- Produces: `ValueTask<ExportAttemptResult> ResilienceExecutor.ExecuteAsync(string signal, Func<CancellationToken, ValueTask<bool>> attempt, DateTimeOffset deadline, CancellationToken cancellationToken = default)`; concurrent provider drains using a single deadline; no process-wide OTel environment writes.

- [ ] **Step 1: Characterize disconnected resilience and deadline multiplication**

Run:

```bash
rg -n 'Resilience|Retry|Circuit|Environment\.SetEnvironmentVariable|EnvOverride|ForceFlush|Shutdown|Dispose|lock \(Gate\)' csharp/src
```

Expected: settings live in core but do not wrap real export attempts, OTel setup mutates process environment, sequential drains each receive the full timeout, or disposal occurs under `Gate`.

- [ ] **Step 2: Add failing retry, health, deadline, ownership, and environment tests**

```csharp
[Fact]
public async Task ExporterRetriesAndUpdatesHealth()
{
    var attempts = 0;
    var result = await TestBackend.ExecuteAsync("logs", _ =>
        ValueTask.FromResult(++attempts == 3), DateTimeOffset.UtcNow.AddSeconds(1));
    Assert.True(result.Succeeded);
    Assert.Equal(3, attempts);
    Assert.Equal(2UL, Health.Snapshot().LogsRetries);
    Assert.True(Health.Snapshot().LogsLatencySeconds >= 0);
}

[Fact]
public async Task ShutdownUsesOneDeadlineAndDrainsSignalsTogether()
{
    var drains = new BlockingDrains(TimeSpan.FromSeconds(5));
    var elapsed = await drains.ShutdownWithTimeout(TimeSpan.FromMilliseconds(100));
    Assert.InRange(elapsed.TotalMilliseconds, 50, 500);
    Assert.True(drains.MaximumConcurrent >= 3);
}

[Fact]
public void SetupDoesNotMutateOtelEnvironment()
{
    var before = Environment.GetEnvironmentVariables().Cast<DictionaryEntry>()
        .Where(e => e.Key.ToString()!.StartsWith("OTEL_", StringComparison.Ordinal)).ToArray();
    using var runtime = Telemetry.Setup(TestData.OtelConfig);
    var after = Environment.GetEnvironmentVariables().Cast<DictionaryEntry>()
        .Where(e => e.Key.ToString()!.StartsWith("OTEL_", StringComparison.Ordinal)).ToArray();
    Assert.Equal(before, after);
}
```

Add a host-owned provider test proving shutdown returns `NotOwned` and never calls dispose.

- [ ] **Step 3: Verify integration lifecycle tests fail**

Run:

```bash
dotnet test csharp/tests/Provide.Telemetry.OpenTelemetry.Tests/Provide.Telemetry.OpenTelemetry.Tests.csproj --filter 'ResilientExporter|ProviderDeadline|ProcessEnvironment'
```

Expected: retry health is disconnected, total drain time exceeds one deadline, environment changes, or owned/adopted disposal is wrong.

- [ ] **Step 4: Implement real resilient attempts and deadline-based drains**

```csharp
public async ValueTask<ExportAttemptResult> ExecuteAsync(
    string signal,
    Func<CancellationToken, ValueTask<bool>> attempt,
    DateTimeOffset deadline,
    CancellationToken cancellationToken = default)
{
    for (var index = 0; ; index++) {
        var remaining = deadline - TimeProvider.GetUtcNow();
        if (remaining <= TimeSpan.Zero) return ExportAttemptResult.TimedOut(index);
        using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        linked.CancelAfter(remaining);
        var started = Stopwatch.GetTimestamp();
        try { if (await attempt(linked.Token)) return ExportAttemptResult.Success(index + 1); }
        finally { Health.RecordAttempt(signal, Stopwatch.GetElapsedTime(started)); }
        if (index >= Policy(signal).Retries || !Circuit(signal).AllowAttempt())
            return ExportAttemptResult.Failed(index + 1);
        Health.IncrementRetries(signal);
        await DelayBoundedByDeadline(signal, index, deadline, linked.Token);
    }
}
```

Wrap real log, trace, and metric export calls. Build exporters from explicit options instead of environment mutation. For flush/shutdown, calculate `deadline` once, detach owned providers under the lifecycle lock, start signal drain tasks together, await them against remaining time, then dispose owned providers outside the lock. Preserve installed providers after flush; detach only during shutdown.

- [ ] **Step 5: Run integration, lifecycle, and collector tests**

Run:

```bash
dotnet test csharp/Provide.Telemetry.sln --filter 'Resilien|Retry|Circuit|Deadline|Lifecycle|Ownership|Environment'
bash ci/verify-collector-signals.sh csharp
```

Expected: retries drive actual attempts, health transitions are exact, lifecycle returns within one deadline, collector signals arrive, and no global environment value changes.

- [ ] **Step 6: Commit C# resilient lifecycle integration**

```bash
git add csharp/src csharp/tests/Provide.Telemetry.OpenTelemetry.Tests
git commit -m "feat(csharp): connect resilient exporters and bounded drains"
```

### Task 16: Enforce five-language artifact, quality, documentation, and release gates

**Files:**
- Modify: `spec/check_config_parity.py`
- Modify: `spec/behavioral_fixtures.yaml`
- Modify: `spec/runtime_probe_fixtures.yaml`
- Modify: `spec/contract_fixtures.yaml`
- Modify: `spec/fixture_test_ids.yaml`
- Modify: `spec/probes/config_probe_python.py`
- Modify: `spec/probes/config_probe_typescript.ts`
- Modify: `spec/probes/config_probe_go/main.go`
- Modify: `rust/examples/config_probe.rs`
- Modify: `csharp/probes/ConfigProbe/Program.cs`
- Create: `csharp/stryker-config.json`
- Create: `csharp/.config/dotnet-tools.json`
- Modify: `scripts/check_version_sync.py`
- Create: `scripts/check_csharp_coverage.py`
- Modify: `tests/tooling/test_check_version_sync.py`
- Create: `tests/tooling/test_check_csharp_coverage.py`
- Modify: `ci/verify-collector-signals.sh`
- Modify: `ci/verify-collector-content.py`
- Modify: `.github/workflows/ci-csharp.yml`
- Modify: `.github/workflows/ci-mutation.yml`
- Modify: `.github/workflows/ci-surface.yml`
- Modify: `.github/workflows/release.yml`
- Modify: `README.md`
- Modify: `csharp/README.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all preceding runtime implementations and probes.
- Produces: one five-language config comparator; two C# NuGet artifacts at exactly version `0.8.0`; 100% C# owned line/branch gate; Stryker.NET 4.16.0 mutation gate; five-language collector, consumer, docs, version, and release evidence.

- [ ] **Step 1: Characterize current quality and release omissions**

Run:

```bash
rg -n '73|53|mutation|stryker|csharp|all four|four languages|Provide.Telemetry.OpenTelemetry' .github README.md docs csharp scripts/check_version_sync.py
dotnet tool list --tool-manifest csharp/.config/dotnet-tools.json || true
```

Expected: C# coverage floors are 73/53 or equivalent, mutation/release jobs omit C#, version sync knows one C# artifact, and docs claim four SDKs.

- [ ] **Step 2: Add failing config-probe and two-package version tests**

```python
def test_csharp_package_versions_are_exactly_synchronized(tmp_path):
    versions = read_versions(REPOSITORY_ROOT)
    assert versions["csharp-core"] == versions["repository"]
    assert versions["csharp-otel"] == versions["repository"]


def test_all_config_probes_match_schema():
    reports = run_config_probes(("python", "typescript", "go", "rust", "csharp"))
    assert {report.language for report in reports} == {
        "python", "typescript", "go", "rust", "csharp"
    }
    assert all(report.diff == [] for report in reports)
```

Add workflow strictness tests that parse YAML and assert C# coverage thresholds are 100/100, the mutation job restores tool version 4.16.0 and runs `dotnet stryker`, and release packs both C# projects.

Add `check_csharp_coverage.py --root <path> --line <percent> --branch <percent>` to load every Cobertura report below the root, merge owned `Provide.Telemetry` and `Provide.Telemetry.OpenTelemetry` classes by source file, and fail when either aggregate falls below its threshold. Its unit test supplies two small Cobertura XML documents and asserts a 99.9% line or branch value returns exit code 1 at a 100% threshold.

- [ ] **Step 3: Run tooling tests and verify red**

Run:

```bash
uv run pytest tests/tooling/test_check_version_sync.py tests/tooling/test_check_csharp_coverage.py tests/tooling/test_ci_workflow_strictness.py -q
python spec/check_config_parity.py --strict
```

Expected: absent probes, second-package version, coverage threshold, mutation manifest, and release job cause failures.

- [ ] **Step 4: Implement executable probes and strict artifact gates**

Each config probe emits the same JSON shape:

```json
{"language":"csharp","entries":{"logging.level":{"type":"string","default":"INFO","applicable":true}}}
```

`check_config_parity.py` loads `telemetry-api.yaml`, runs all five probes, compares exact name/type/default/applicability tuples, and exits nonzero on missing runtimes or diffs. Register `recursive_hardening`, `receipt_signing`, `receipt_delivery`, `lifecycle_generation`, and `signal_pipeline_order` in the shared behavioral/runtime/contract fixtures, and map each category to the real fixture-driven tests created in Tasks 4, 6, 7-8, 10, and 13-15. Pin the tool manifest:

```json
{
  "version": 1,
  "isRoot": true,
  "tools": {
    "dotnet-stryker": {
      "version": "4.16.0",
      "commands": ["dotnet-stryker"]
    }
  }
}
```

Configure Coverlet to include `[Provide.Telemetry]*` and `[Provide.Telemetry.OpenTelemetry]*`, exclude generated code, and fail below 100% line or branch. Configure Stryker for the two owned projects and use only reasoned `mutate` exclusions for generated assembly metadata. Update version sync, collector content assertions, package consumers, solution paths, CI surface paths, and release jobs for both NuGet packages at `0.8.0`.

Run Stryker from `csharp/`, where solution mode discovers both source projects, with this configuration:

```json
{
  "stryker-config": {
    "solution": "Provide.Telemetry.sln",
    "reporters": ["progress", "json"],
    "mutation-level": "Complete",
    "thresholds": { "high": 100, "low": 100, "break": 100 },
    "mutate": [
      "src/Provide.Telemetry/**/*.cs",
      "src/Provide.Telemetry.OpenTelemetry/**/*.cs",
      "!**/obj/**",
      "!**/*.g.cs"
    ]
  }
}
```

- [ ] **Step 5: Update five-language documentation and release notes**

Document five SDKs, the canonical config vocabulary, no legacy C# aliases, snake_case records, receipt sink requirement, 26 health fields, C# package selection, core-only and OTel examples, and the `0.8.0` breaking changes. Every capability-matrix `core` cell must name its executable test or probe ID.

- [ ] **Step 6: Run the whole repository verification matrix**

Run:

```bash
python spec/validate_conformance.py
python spec/check_fixture_test_ids.py
python spec/check_config_parity.py --strict
python spec/run_behavioral_parity.py --strict
uv run pytest -q
uv run coverage run -m pytest -q && uv run coverage report --fail-under=100
npm --prefix typescript test && npm --prefix typescript run lint && npm --prefix typescript run typecheck && npm --prefix typescript run build
bash ci/verify-npm-consumer-package.sh
(cd go && go test -race ./...)
(cd go/otel && go test -race ./...)
(cd rust && cargo fmt --check && cargo clippy --all-features --all-targets -- -D warnings && cargo test --all-features --all-targets)
dotnet restore csharp/Provide.Telemetry.sln
dotnet build csharp/Provide.Telemetry.sln --no-restore -warnaserror
dotnet test csharp/Provide.Telemetry.sln --no-build --collect:'XPlat Code Coverage'
python scripts/check_csharp_coverage.py --root csharp --line 100 --branch 100
dotnet tool restore --tool-manifest csharp/.config/dotnet-tools.json
(cd csharp && dotnet stryker --config-file stryker-config.json)
bash ci/verify-collector-signals.sh all
python scripts/check_version_sync.py
git diff --check
```

Expected: every command passes; C# reports 100% owned line and branch coverage and zero surviving owned-code mutants; all five collector signals and both C# packages verify.

- [ ] **Step 7: Perform a final branch review against the approved design**

Run:

```bash
git diff --stat 19fbbb7...HEAD
git diff --check 19fbbb7...HEAD
rg -n 'all four|four languages|PROVIDE_TELEMETRY_ENVIRONMENT|service\.name|trace\.id' README.md docs csharp/src spec
git status --short
```

Expected: no stale four-language or legacy-wire claims, no whitespace errors, and only the preserved user modification to `rust/src/resilience_state_tests.rs` remains unstaged. Review every critical/high finding in the approved design and record its passing regression test in `CHANGELOG.md` under `0.8.0`.

- [ ] **Step 8: Commit release rigor and documentation**

```bash
git add spec scripts tests/tooling ci .github README.md docs csharp/README.md csharp/stryker-config.json csharp/.config csharp/probes/ConfigProbe CHANGELOG.md
git commit -m "release: enforce rigorous five-language parity"
```

## Completion Evidence

The implementation is complete only when Task 16 Step 6 has fresh passing output, Task 16 Step 7 finds no unresolved critical or important issue, both C# packages build from packed artifacts, and `git status --short` shows the user's pre-existing Rust change was not absorbed into any task commit.
