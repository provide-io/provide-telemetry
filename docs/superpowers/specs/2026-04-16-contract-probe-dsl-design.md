# Contract Probe DSL — Design Spec

## Goal

Replace shortcut-based parity probes with a step-based contract DSL that exercises real public APIs and catches cross-language drift at the exact seams that tend to regress (propagation-to-logger correlation, trace-field precedence, config validation, lifecycle state).

## Background

The current parity layer has three validation tiers:
1. `validate_conformance.py` — checks exported symbol names (low signal)
2. `run_behavioral_parity.py` — runs per-language fixture tests (intra-language correctness)
3. `parity_probe_support.py` — compares cross-language behavior, but probes use `setTraceContext` directly instead of `bindPropagationContext`, missing the exact integration seams that drifted

This session fixed multiple bugs that the existing probes failed to catch: TS/Go propagation not bridging to trace context, TS context overwriting live trace IDs, TS silently clamping invalid config, and lifecycle state leaking across shutdown.

## Fixture Format

Contract test cases live in `spec/contract_fixtures.yaml`. Each case is a sequence of operations with expected outputs:

```yaml
contract_cases:
  propagation_to_logger_correlation:
    description: "Propagated W3C trace IDs appear on log records"
    steps:
      - op: setup
      - op: bind_propagation
        traceparent: "00-aabbccdd11223344aabbccdd11223344-aabb001122334455-01"
        baggage: "userId=alice,tenant=acme"
      - op: emit_log
        message: "test.propagation.ok"
        fields: { event: "test.propagation.ok" }
      - op: capture_log
        into: last_log
      - op: get_trace_context
        into: trace_ctx
      - op: clear_propagation
      - op: shutdown
    expect:
      last_log.trace_id: "aabbccdd11223344aabbccdd11223344"
      last_log.span_id: "aabb001122334455"
      last_log.message: "test.propagation.ok"
      last_log["baggage.userId"]: "alice"
      last_log["baggage.tenant"]: "acme"
      trace_ctx.trace_id: "aabbccdd11223344aabbccdd11223344"
```

The `into` field names a variable that stores the operation result. The `expect` block maps dotted paths to expected values. The harness compares these across all four languages.

## Supported Operations

| Operation | Parameters | Stores in `into` | What it does |
|-----------|-----------|-------------------|-------------|
| `setup` | `overrides` (optional dict) | — | Call `setupTelemetry(overrides)` |
| `setup_invalid` | `overrides` (dict) | `{raised, error}` | Call `setupTelemetry(overrides)`, expect error |
| `shutdown` | — | — | Call `shutdownTelemetry()` |
| `bind_propagation` | `traceparent`, `baggage` (optional) | — | Call `bindPropagationContext(extracted context)` |
| `clear_propagation` | — | — | Call `clearPropagationContext()` |
| `get_trace_context` | `into` | `{trace_id, span_id}` | Read current trace context |
| `bind_context` | `fields` (dict) | — | Bind key-value pairs into log context |
| `emit_log` | `message`, `fields` (optional dict) | — | Log via `getLogger("contract").info(...)` |
| `capture_log` | `into` | Last emitted log record as dict | Capture most recent log output |
| `get_runtime_status` | `into` | RuntimeStatus dict | Read runtime introspection |

## Probe Interpreter

Each language implements a single probe script (~150-200 LOC) that:

1. Reads `PROVIDE_CONTRACT_CASE` env var
2. Loads `spec/contract_fixtures.yaml`
3. Finds the case, executes each step in sequence
4. Stores results in a `variables` map
5. Emits `{ "case": "...", "variables": { ... } }` as JSON to stdout

### Log capture mechanism per language

- **Python**: structlog processor captures to list; read last entry
- **TypeScript**: `makeWriteHook` captures to array; read last entry
- **Go**: custom `slog.Handler` that buffers JSON records
- **Rust**: `enable_json_capture_for_tests` + `take_json_capture` (exists)

### Probe file locations

- `spec/probes/contract_probe_python.py`
- `spec/probes/contract_probe_typescript.ts`
- `spec/probes/contract_probe_go/main.go`
- `rust/examples/contract_probe.rs`

### YAML dependency

YAML parsing is dev/test-only in all languages. It does not ship in any package:

| Language | YAML dep | Location | Ships? |
|----------|----------|----------|--------|
| Python | PyYAML | `[dependency-groups] dev` | No |
| TypeScript | yaml | `devDependencies` | No |
| Go | gopkg.in/yaml.v3 | go.mod (test files only) | No |
| Rust | serde_yaml | `[dev-dependencies]` | No |

## Harness and Comparison

New function in `spec/parity_probe_support.py`:

```
run_contract_cases(repo, selected_languages, selected_cases)
```

For each case:
1. Spawn all 4 language probes in parallel with `PROVIDE_CONTRACT_CASE=<id>`
2. Parse JSON output from each
3. Validate output shape: `{ "case": "...", "variables": { ... } }`
4. For each path in `expect`, verify all languages produced the expected value
5. Cross-compare: for all variables, all languages must agree

Invoked via:
```bash
uv run python spec/run_behavioral_parity.py --check-contracts
```

Additive — existing `--check-output` stays unchanged.

### Failure output

```
FAIL: propagation_to_logger_correlation
  last_log.trace_id:
    python:     "aabbccdd11223344aabbccdd11223344"
    typescript: ""          <- DIVERGED
    go:         "aabbccdd11223344aabbccdd11223344"
    rust:       "aabbccdd11223344aabbccdd11223344"
```

## Initial Contract Cases

| Case ID | Tests | Catches |
|---------|-------|---------|
| `propagation_to_logger_correlation` | bind_propagation -> emit_log -> verify trace/span/baggage on record | TS/Go propagation bridge bug |
| `trace_field_precedence` | bind_context(spoofed trace_id) -> bind_propagation(real) -> emit_log -> real wins | TS context overwrite bug |
| `setup_invalid_overrides` | setup_invalid({samplingLogsRate: -1}) -> verify raised=true | TS clamping-vs-rejecting |
| `shutdown_re_setup` | setup -> shutdown -> setup(new config) -> get_runtime_status -> verify new state | Lifecycle state cleanup |
| `baggage_auto_injection` | bind_propagation(baggage with properties) -> emit_log -> verify parsed keys, properties stripped | Baggage parsing + injection |
| `propagation_cleanup` | bind_propagation -> clear_propagation -> emit_log -> verify trace/baggage absent | Context leak on clear |

## Migration from Existing Probes

- **Migrate to contract DSL**: `invalid_config` -> `setup_invalid_overrides`, `shutdown_re_setup` -> `shutdown_re_setup`, `lazy_init_logger` -> replaced by `propagation_to_logger_correlation`
- **Keep as runtime probes**: `strict_schema_rejection`, `required_keys_rejection`, `fail_open_exporter_init`, `signal_enablement` (require mocking/env-poisoning that doesn't fit step DSL)
- **No immediate deletions**: old runtime probes run alongside new contract probes. Remove migrated cases after 2-3 green CI cycles.
- **Log output probes unchanged**: `emit_log_*` scripts serve a different purpose (output format comparison)

## File Checklist

**Create:**
- `spec/contract_fixtures.yaml` — 6 initial cases
- `spec/probes/contract_probe_python.py` — Python interpreter (~150 LOC)
- `spec/probes/contract_probe_typescript.ts` — TypeScript interpreter (~150 LOC)
- `spec/probes/contract_probe_go/main.go` — Go interpreter (~200 LOC)
- `rust/examples/contract_probe.rs` — Rust interpreter (~200 LOC)

**Modify:**
- `spec/parity_probe_support.py` — add `run_contract_cases()` and contract probe runners
- `spec/run_behavioral_parity.py` — add `--check-contracts` flag
- `rust/Cargo.toml` — add `serde_yaml` to dev-dependencies

**Unchanged:**
- `spec/runtime_probe_fixtures.yaml` — existing runtime probes stay
- `spec/probes/emit_log_*` — log output probes stay
- `spec/validate_conformance.py` — symbol checking stays

## Success Criteria

1. `uv run python spec/run_behavioral_parity.py --check-contracts` passes with all 6 cases green across all 4 languages
2. Each case exercises the real public API (no `setTraceContext` shortcuts)
3. Adding a new contract case requires editing only `spec/contract_fixtures.yaml`
4. All probe scripts under 500 LOC
5. All files have SPDX headers
