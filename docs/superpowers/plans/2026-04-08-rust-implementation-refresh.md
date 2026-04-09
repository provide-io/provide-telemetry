# Rust Implementation Refresh Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class Rust implementation of `provide-telemetry` that passes spec conformance, shares repo-level versioning and parity fixtures, and participates in cross-language tracing verification.

**Architecture:** Build a Rust crate under `rust/` with a Python-parity public facade, but stage delivery in two tracks: crate/runtime implementation and monorepo integration. Use `tracing`/`tracing-subscriber` for the processor pipeline, optional OpenTelemetry via Cargo features, and a guard-based context API so Rust preserves task-safe context semantics without copying Python's `contextvars` literally.

**Tech Stack:** Rust 1.81+, edition 2021, `tracing`, `tracing-subscriber`, `serde`, `serde_json`, `thiserror`, `sha2`, `regex`, `tokio`, optional `opentelemetry*` crates, Python repo tooling (`uv`, pytest), existing spec/parity fixtures under `spec/` and `e2e/`.

---

## File Structure

### New Rust crate

- `rust/Cargo.toml` — crate metadata, features, dependencies, lint policy
- `rust/src/lib.rs` — public facade and re-exports
- `rust/src/config.rs` — `TelemetryConfig`, `RuntimeOverrides`, env parsing, redaction helpers
- `rust/src/errors.rs` — `TelemetryError`, `ConfigurationError`, `EventSchemaError`
- `rust/src/runtime.rs` — active snapshot, hot reload, provider-change detection
- `rust/src/setup.rs` — idempotent setup/shutdown coordinator
- `rust/src/context.rs` — bound context + session context guard API
- `rust/src/tracing.rs` — tracer facade, trace wrapper, trace context helpers
- `rust/src/logger.rs` — logger facade, subscriber/layer composition, default logger instance
- `rust/src/metrics.rs` — meter facade + fallback instruments
- `rust/src/propagation.rs` — W3C extraction/binding
- `rust/src/sampling.rs` — per-signal sampling policies
- `rust/src/backpressure.rs` — queue policy + bounded permit abstraction
- `rust/src/resilience.rs` — exporter policy + retry/timeout/circuit breaker
- `rust/src/pii.rs` — PII rules, secret patterns, sanitization
- `rust/src/cardinality.rs` — per-key distinct-value guards
- `rust/src/health.rs` — health counters and snapshot
- `rust/src/schema.rs` — `event`, `event_name`, `Event`
- `rust/src/slo.rs` — optional RED/USE helpers and error classification
- `rust/src/otel.rs` — OTel feature-gated provider wiring
- `rust/src/testing.rs` — reset hooks and test helpers

### Rust tests

- `rust/tests/config_test.rs`
- `rust/tests/runtime_test.rs`
- `rust/tests/logger_test.rs`
- `rust/tests/tracing_test.rs`
- `rust/tests/metrics_test.rs`
- `rust/tests/propagation_test.rs`
- `rust/tests/parity_test.rs`
- `rust/tests/integration_test.rs`

### Monorepo integration

- `spec/validate_conformance.py` — add Rust export collection and CLI support
- `spec/behavioral_fixtures.yaml` — extend only when Rust exposes fixture gaps
- `scripts/check_version_sync.py` — keep Rust version path exercised in CI
- `e2e/test_cross_language_trace_e2e.py` — generalize harness for Rust participant
- `e2e/backends/` — add Rust backend launcher or backend binary contract docs
- `.github/workflows/ci-rust.yml` — Rust lint/test/feature matrix
- `.github/workflows/ci-spec.yml` or existing spec workflow — ensure Rust conformance runs
- `docs/ARCHITECTURE.md` / `docs/API.md` / `docs/INTERNALS.md` — update language inventory and Rust-specific notes once implementation exists

---

## Design Constraints

### 1. Treat Rust as a monorepo citizen, not a sidecar

Rust is not complete when `cargo test` passes. It is complete when:

- `spec/validate_conformance.py` can check Rust
- shared version sync sees `rust/Cargo.toml`
- parity fixtures have a Rust runner
- cross-language tracing E2E includes Rust as a client or server

### 2. Do not mirror Python internals mechanically

Python's architecture is the behavioral reference, not the implementation template. Rust should preserve:

- idempotent process setup
- hot vs cold config boundaries
- per-task context isolation
- graceful OTel degradation
- deterministic schema/PII/sampling/backpressure behavior

But Rust should express those using:

- RAII guards instead of global mutable context without lifetime control
- explicit feature flags for optional OTel support
- `Result`-based errors rather than exception-style control flow

### 3. Use guard-based context APIs

The current repo contract requires functions named `bind_context`, `unbind_context`, `clear_context`, `bind_session_context`, `get_session_id`, and `clear_session_context`. In Rust, the safe shape should be:

```rust
pub struct ContextGuard { /* restores previous state on Drop */ }

pub fn bind_context(fields: impl IntoIterator<Item = (String, serde_json::Value)>) -> ContextGuard;
pub fn bind_session_context(session_id: impl Into<String>) -> ContextGuard;
```

This keeps the required symbol names while avoiding the dead-end `tokio::task_local!`-only API from the prior plan.

### 4. Phase delivery around observable behavior

Phase order:

1. conformance + core types
2. fallback runtime behavior
3. optional OTel integration
4. parity fixtures
5. cross-language E2E

That order keeps failures local and makes CI useful earlier.

---

## Task 1: Add Rust To Repo-Level Gates

**Files:**
- Create: `rust/Cargo.toml`, `rust/src/lib.rs`
- Modify: `spec/validate_conformance.py`
- Modify: `.github/workflows/ci-rust.yml` or create if absent

- [ ] **Step 1: Create the minimal crate skeleton**

```toml
[package]
name = "provide-telemetry"
version = "0.4.0"
edition = "2021"
rust-version = "1.81"

[lib]
name = "provide_telemetry"
path = "src/lib.rs"
```

- [ ] **Step 2: Export empty stubs for every required symbol in `rust/src/lib.rs`**

```rust
pub struct TelemetryError;
pub struct ConfigurationError;
pub struct EventSchemaError;

pub fn setup_telemetry() {}
pub fn shutdown_telemetry() {}
```

Expected: enough public surface exists for the conformance parser to target.

- [ ] **Step 3: Extend the conformance checker for Rust**

```python
def _get_rust_exports() -> set[str]:
    lib_rs = _REPO_ROOT / "rust" / "src" / "lib.rs"
    if not lib_rs.exists():
        return set()
    text = lib_rs.read_text(encoding="utf-8")
    patterns = (
        r"^\s*pub\s+(?:async\s+)?fn\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        r"^\s*pub\s+struct\s+([A-Z][A-Za-z0-9_]*)",
        r"^\s*pub\s+enum\s+([A-Z][A-Za-z0-9_]*)",
        r"^\s*pub\s+type\s+([A-Z][A-Za-z0-9_]*)",
        r"^\s*pub\s+static\s+([A-Z_][A-Z0-9_]*)",
    )
    exports: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.MULTILINE):
            exports.add(match.group(1))
    return exports
```

- [ ] **Step 4: Add `rust` to CLI choices and default language list**

Run: `uv run python spec/validate_conformance.py --lang rust`

Expected: checker runs and reports concrete missing exports instead of "not yet supported".

- [ ] **Step 5: Commit after the gate is live**

```bash
git add rust/Cargo.toml rust/src/lib.rs spec/validate_conformance.py .github/workflows/ci-rust.yml
git commit -m "build: add rust conformance gate scaffolding"
```

### Exit Criteria

- `spec/validate_conformance.py --lang rust` executes
- CI has a Rust workflow entry point, even if tests are still mostly stubs

---

## Task 2: Define Public API, Config, And Errors

**Files:**
- Modify: `rust/src/lib.rs`
- Create: `rust/src/config.rs`
- Create: `rust/src/errors.rs`
- Test: `rust/tests/config_test.rs`

- [ ] **Step 1: Mirror required repo types exactly**

```rust
pub use config::{RuntimeOverrides, TelemetryConfig};
pub use errors::{ConfigurationError, EventSchemaError, TelemetryError};
```

- [ ] **Step 2: Implement config models matching repo semantics**

```rust
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct TelemetryConfig {
    pub service_name: String,
    pub environment: String,
    pub version: String,
    pub strict_schema: bool,
    pub pii_max_depth: usize,
    // nested logging/tracing/metrics/event_schema/sampling/backpressure/exporter/slo/security
}
```

- [ ] **Step 3: Port env parsing rules before runtime code**

Run targeted checks against known repo behaviors:

```bash
cd rust
cargo test config_test -- --nocapture
```

Expected: parsing covers `PROVIDE_*` and `OTEL_*` variables, including header decoding and defaults.

- [ ] **Step 4: Model distinct error types, not aliases**

```rust
#[derive(thiserror::Error, Debug, Clone)]
#[error("{message}")]
pub struct ConfigurationError { pub message: String }
```

Reason: the spec and repo treat these as distinct exported types.

- [ ] **Step 5: Commit**

```bash
git add rust/src/lib.rs rust/src/config.rs rust/src/errors.rs rust/tests/config_test.rs
git commit -m "feat: add rust config and error surface"
```

---

## Task 3: Implement Runtime Snapshot And Lifecycle State

**Files:**
- Create: `rust/src/runtime.rs`
- Create: `rust/src/setup.rs`
- Test: `rust/tests/runtime_test.rs`

- [ ] **Step 1: Add a single runtime state container**

```rust
static ACTIVE_CONFIG: OnceLock<RwLock<Option<TelemetryConfig>>> = OnceLock::new();
static SETUP_STATE: OnceLock<Mutex<SetupState>> = OnceLock::new();
```

- [ ] **Step 2: Preserve hot/cold config split from the repo docs**

```rust
fn provider_config_changed(current: &TelemetryConfig, target: &TelemetryConfig) -> bool {
    current.service_name != target.service_name
        || current.environment != target.environment
        || current.version != target.version
        || current.tracing != target.tracing
        || current.metrics != target.metrics
}
```

- [ ] **Step 3: Implement idempotent setup and serialized shutdown**

Run:

```bash
cd rust
cargo test runtime_test::setup_is_idempotent
cargo test runtime_test::shutdown_clears_setup_state
```

Expected: concurrent callers see one setup and safe teardown.

- [ ] **Step 4: Implement `update_runtime_config`, `reload_runtime_from_env`, and `reconfigure_telemetry`**

```rust
pub fn update_runtime_config(overrides: RuntimeOverrides) -> Result<TelemetryConfig, TelemetryError> { /* ... */ }
pub fn reconfigure_telemetry(config: Option<TelemetryConfig>) -> Result<TelemetryConfig, TelemetryError> { /* ... */ }
```

- [ ] **Step 5: Commit**

```bash
git add rust/src/runtime.rs rust/src/setup.rs rust/tests/runtime_test.rs
git commit -m "feat: add rust lifecycle and runtime state"
```

---

## Task 4: Solve Context, Session, And Trace Context Semantics

**Files:**
- Create: `rust/src/context.rs`
- Create: `rust/src/tracing.rs`
- Test: `rust/tests/tracing_test.rs`

- [ ] **Step 1: Implement scoped context storage with restoration-on-drop**

```rust
pub struct ContextSnapshot {
    fields: BTreeMap<String, serde_json::Value>,
    session_id: Option<String>,
    trace_id: Option<String>,
    span_id: Option<String>,
}
```

- [ ] **Step 2: Back the storage with a runtime-aware abstraction**

Preferred approach (note: `RefCell` makes the task `!Send`; use `Mutex` or restructure to avoid interior mutability if tasks must cross thread boundaries on Tokio's multi-threaded scheduler):

```rust
tokio::task_local! {
    static TASK_CONTEXT: Mutex<ContextSnapshot>;
}
```

Fallback for non-Tokio callers:

```rust
thread_local! {
    static THREAD_CONTEXT: RefCell<ContextSnapshot> = RefCell::new(ContextSnapshot::default());
}
```

- [ ] **Step 3: Export required functions with Rust-safe signatures**

```rust
pub fn bind_context(fields: impl IntoIterator<Item = (String, Value)>) -> ContextGuard;
pub fn unbind_context(keys: &[&str]) -> ContextGuard;
pub fn clear_context() -> ContextGuard;
pub fn get_trace_context() -> BTreeMap<String, Option<String>>;
```

- [ ] **Step 4: Prove async isolation explicitly**

Run:

```bash
cd rust
cargo test tracing_test::context_isolated_across_tokio_tasks
cargo test tracing_test::trace_context_survives_await_boundaries
```

Expected: two tasks can carry different request/session/trace values without cross-talk.

- [ ] **Step 5: Commit**

```bash
git add rust/src/context.rs rust/src/tracing.rs rust/tests/tracing_test.rs
git commit -m "feat: add rust context and trace context model"
```

---

## Task 5: Implement Deterministic Policy Modules First

**Files:**
- Create: `rust/src/sampling.rs`
- Create: `rust/src/backpressure.rs`
- Create: `rust/src/resilience.rs`
- Create: `rust/src/health.rs`
- Test: `rust/tests/integration_test.rs`

- [ ] **Step 1: Implement per-signal policy registries**

```rust
pub enum Signal { Logs, Traces, Metrics }
```

```rust
pub struct SamplingPolicy { pub default_rate: f64, pub overrides: BTreeMap<String, f64> }
pub struct QueuePolicy { pub logs_maxsize: usize, pub traces_maxsize: usize, pub metrics_maxsize: usize }
pub struct ExporterPolicy { pub retries: u32, pub backoff_seconds: f64, pub timeout_seconds: f64, pub fail_open: bool, pub allow_blocking_in_event_loop: bool }
```

- [ ] **Step 2: Make queue size `0` truly unlimited**

```rust
enum QueueLimiter {
    Unlimited,
    Bounded(Arc<Semaphore>),
}
```

- [ ] **Step 3: Build resilience as a reusable wrapper**

```rust
pub async fn run_with_resilience<F, T>(signal: Signal, op: F) -> Result<Option<T>, TelemetryError>
where
    F: Future<Output = Result<T, TelemetryError>>;
```

- [ ] **Step 4: Record health counters from every policy branch**

Run:

```bash
cd rust
cargo test integration_test::sampling_drop_increments_health
cargo test integration_test::bounded_queue_drop_increments_health
cargo test integration_test::circuit_breaker_trips_after_three_timeouts
```

- [ ] **Step 5: Commit**

```bash
git add rust/src/sampling.rs rust/src/backpressure.rs rust/src/resilience.rs rust/src/health.rs rust/tests/integration_test.rs
git commit -m "feat: add rust runtime policy modules"
```

---

## Task 6: Implement Schema, PII, Cardinality, And Event Construction

**Files:**
- Create: `rust/src/schema.rs`
- Create: `rust/src/pii.rs`
- Create: `rust/src/cardinality.rs`
- Test: `rust/tests/parity_test.rs`

- [ ] **Step 1: Port the observable rules before logger wiring**

```rust
pub struct Event {
    pub domain: String,
    pub action: String,
    pub resource: Option<String>,
    pub status: String,
}
```

- [ ] **Step 2: Match canonical default-sensitive keys and secret-pattern behavior**

```rust
const DEFAULT_SENSITIVE: &[&str] = &[
    "password", "passwd", "secret", "token", "api_key", "apikey", "auth", "authorization",
    "credential", "private_key", "ssn", "credit_card", "creditcard", "cvv", "pin",
    "account_number", "cookie",
];
```

- [ ] **Step 3: Keep cardinality behavior deterministic**

```rust
pub fn register_cardinality_limit(key: impl Into<String>, limit: CardinalityLimit) {
    let max_values = limit.max_values.max(1);
    let ttl_seconds = limit.ttl_seconds.max(1.0);
}
```

- [ ] **Step 4: Drive these modules from shared parity fixtures**

Run:

```bash
cd rust
cargo test parity_test::pii_hash_matches_fixture
cargo test parity_test::event_dars_matches_fixture
cargo test parity_test::propagation_limits_match_fixture
```

- [ ] **Step 5: Commit**

```bash
git add rust/src/schema.rs rust/src/pii.rs rust/src/cardinality.rs rust/tests/parity_test.rs
git commit -m "feat: add rust schema pii and cardinality behavior"
```

---

## Task 7: Build Logger, Tracer, And Metric Facades In Fallback Mode First

**Files:**
- Create: `rust/src/logger.rs`
- Create: `rust/src/metrics.rs`
- Modify: `rust/src/tracing.rs`
- Test: `rust/tests/logger_test.rs`
- Test: `rust/tests/metrics_test.rs`

- [ ] **Step 1: Build a subscriber/layer pipeline that mirrors repo order**

Target order:

```text
context -> trace/session merge -> standard fields -> error fingerprint ->
sampling -> schema -> pii -> renderer/export
```

- [ ] **Step 2: Export package-level default instances**

```rust
pub static LOGGER: OnceLock<TelemetryLogger> = OnceLock::new();
pub static TRACER: OnceLock<TelemetryTracer> = OnceLock::new();
```

- [ ] **Step 3: Implement metrics fallback wrappers before real OTel**

```rust
pub fn counter(name: &str, description: Option<&str>, unit: Option<&str>) -> Counter;
pub fn gauge(name: &str, description: Option<&str>, unit: Option<&str>) -> Gauge;
pub fn histogram(name: &str, description: Option<&str>, unit: Option<&str>) -> Histogram;
```

- [ ] **Step 4: Verify that logs/spans/metrics still function with no OTel feature enabled**

Run:

```bash
cd rust
cargo test logger_test::logging_works_without_otel
cargo test tracing_test::trace_wrapper_works_without_otel
cargo test metrics_test::fallback_instruments_record_values
```

- [ ] **Step 5: Commit**

```bash
git add rust/src/logger.rs rust/src/metrics.rs rust/src/tracing.rs rust/tests/logger_test.rs rust/tests/metrics_test.rs
git commit -m "feat: add rust fallback signal facades"
```

---

## Task 8: Add Optional OpenTelemetry Wiring

**Files:**
- Create: `rust/src/otel.rs`
- Modify: `rust/Cargo.toml`
- Modify: `rust/src/setup.rs`
- Test: `rust/tests/integration_test.rs`

- [ ] **Step 1: Add a single `otel` feature**

```toml
[features]
default = []
otel = [
  "dep:opentelemetry",
  "dep:opentelemetry_sdk",
  "dep:opentelemetry-otlp",
  "dep:tracing-opentelemetry",
]
```

- [ ] **Step 2: Keep the feature boundary explicit**

```rust
#[cfg(feature = "otel")]
pub(crate) fn setup_otel(config: &TelemetryConfig) -> Result<(), TelemetryError> { /* ... */ }

#[cfg(not(feature = "otel"))]
pub(crate) fn setup_otel(_config: &TelemetryConfig) -> Result<(), TelemetryError> {
    Ok(())
}
```

- [ ] **Step 3: Wire tracing and metrics provider setup under the same lifecycle lock**

Run:

```bash
cd rust
cargo test --features otel integration_test::setup_registers_otel_providers
cargo test --features otel integration_test::reconfigure_rejects_provider_replacement_after_install
```

- [ ] **Step 4: Commit**

```bash
git add rust/Cargo.toml rust/src/otel.rs rust/src/setup.rs rust/tests/integration_test.rs
git commit -m "feat: add rust optional otel integration"
```

---

## Task 9: Add Rust Parity And Cross-Language Tests

**Files:**
- Modify: `tests/parity/` docs only if needed
- Create: `rust/tests/parity_test.rs`
- Modify: `e2e/test_cross_language_trace_e2e.py`
- Create: `e2e/backends/rust_cross_language_server/` or `rust/examples/e2e_server.rs`

- [ ] **Step 1: Port shared fixture coverage to Rust**

Focus first on:

- sampling
- PII modes
- propagation guardrails
- event DA(R)S rules
- SLO classification cases

- [ ] **Step 2: Add a Rust client or backend for trace-link E2E**

Preferred initial shape:

```text
TypeScript client -> Rust backend
Rust client -> Python backend
```

That proves Rust can both honor incoming `traceparent` and originate one.

- [ ] **Step 3: Generalize the Python E2E harness instead of forking it**

```python
@pytest.mark.parametrize("backend_lang,client_lang", [("python", "typescript"), ("rust", "typescript"), ("python", "rust")])
def test_cross_language_trace_links_spans(...):
    ...
```

- [ ] **Step 4: Commit**

```bash
git add rust/tests/parity_test.rs e2e/test_cross_language_trace_e2e.py e2e/backends rust/examples
git commit -m "test: add rust parity and cross-language e2e coverage"
```

---

## Task 10: Finish Monorepo Documentation And Release Wiring

**Files:**
- Modify: `docs/API.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/INTERNALS.md`
- Modify: `README.md`
- Modify: `scripts/check_version_sync.py`

- [ ] **Step 1: Update language inventory and repo diagrams**

```markdown
- Rust: `rust/` crate using `tracing` + optional OTel feature
```

- [ ] **Step 2: Document Rust-specific context semantics clearly**

Include:

- guard-based binding
- async-task scope guarantees
- spawned-task limitations and helpers

- [ ] **Step 3: Add final verification commands to docs and CI**

```bash
cd rust
cargo fmt --check
cargo clippy --all-features -- -D warnings
cargo test
cargo test --features otel
uv run python spec/validate_conformance.py --lang rust
uv run python scripts/check_version_sync.py
uv run pytest e2e/test_cross_language_trace_e2e.py -k rust
```

- [ ] **Step 4: Commit**

```bash
git add docs/API.md docs/ARCHITECTURE.md docs/INTERNALS.md README.md scripts/check_version_sync.py
git commit -m "docs: document rust implementation and repo integration"
```

---

## Verification Matrix

### Rust-only

```bash
cd rust
cargo fmt --check
cargo clippy --all-features -- -D warnings
cargo test
cargo test --features otel
```

### Repo-level

```bash
uv run python spec/validate_conformance.py --lang rust
uv run python scripts/check_version_sync.py
uv run pytest tests/parity -q
uv run pytest e2e/test_cross_language_trace_e2e.py -q -k rust
```

### Release readiness

```bash
git diff --stat
git status --short
```

Expected: Rust crate, conformance gate, parity coverage, and E2E wiring are all present and green.

---

## Risks And Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Modeling Python `contextvars` too literally | Fragile or unidiomatic Rust API | Use guard-based binding and test async isolation explicitly |
| Building OTel first | Slow feedback and hard-to-debug failures | Ship fallback runtime first, then gate OTel behind a feature |
| Treating conformance as crate-local | Late CI surprises | Enable Rust in `spec/validate_conformance.py` before feature work |
| Forking parity logic | Behavioral drift from Python/Go/TS | Reuse `spec/behavioral_fixtures.yaml` and existing test vectors |
| Hard-coding E2E for Rust | Duplicate harness maintenance | Generalize the existing Python E2E test to parameterized participants |

---

## Recommended Execution Order

1. Task 1 and Task 2
2. Task 3 and Task 4
3. Task 5 and Task 6
4. Task 7
5. Task 8
6. Task 9
7. Task 10

Plan complete and saved to `docs/superpowers/plans/2026-04-08-rust-implementation-refresh.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
