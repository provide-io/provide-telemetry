# Polyglot Monorepo Design

**Date:** 2026-03-27
**Status:** Draft

## Context

undef-telemetry provides a unified telemetry API (logging, tracing, metrics) with Python and TypeScript implementations that already have full feature parity. The project needs to expand to Go, Rust, and C#/.NET while maintaining API consistency, shared conventions, and cross-language distributed tracing.

The current layout has Python at the repo root (`src/undef/telemetry/`, `pyproject.toml`) and TypeScript in `typescript/`. Both share a `VERSION` file and release from a single git tag. This design preserves that structure and extends it for additional languages.

## Decisions

| Decision | Choice |
|----------|--------|
| Repo layout | Monorepo, Python stays at root |
| API parity enforcement | Shared spec file + cross-language E2E tests |
| Versioning | Shared major.minor, independent patch per language |
| Target languages | Go, Rust, C#/.NET (in addition to existing Python, TypeScript) |

## Directory Structure

```
undef-telemetry/
  VERSION                           # contains major.minor only (e.g. "0.4")
  spec/
    telemetry-api.yaml              # canonical API surface definition
    validate_conformance.py         # reads spec, checks each language's exports
  pyproject.toml                    # Python — unchanged
  src/undef/telemetry/              # Python — unchanged
  tests/                            # Python unit/integration tests — unchanged
  scripts/                          # Python tooling scripts — unchanged
  Makefile                          # Python — unchanged
  typescript/                       # TypeScript — unchanged
  go/
    go.mod                          # module github.com/undef-games/undef-telemetry/go
    telemetry/                      # package telemetry
    telemetry_test.go
  rust/
    Cargo.toml                      # undef-telemetry crate
    src/
      lib.rs
  csharp/
    Undef.Telemetry.sln
    src/Undef.Telemetry/
      Undef.Telemetry.csproj
    tests/Undef.Telemetry.Tests/
  e2e/                              # cross-language E2E tests (promoted from tests/e2e/)
    conftest.py
    test_cross_language_trace.py
    test_browser_trace.py
    backends/
      cross_language_server.py
  docs/
  examples/
    python/                         # existing examples moved here
    typescript/
    go/
    rust/
    csharp/
  .github/workflows/
    ci.yml                          # existing Python + TypeScript (unchanged)
    ci-go.yml
    ci-rust.yml
    ci-csharp.yml
    ci-spec.yml                     # spec conformance + version sync
    ci-cross-language.yml           # cross-language E2E
    release.yml                     # evolves to support per-language tags
```

## Spec File (`spec/telemetry-api.yaml`)

Machine-readable definition of the canonical API surface. Each language implementation is validated against it in CI.

### What the spec defines

- **Functions**: Language-neutral names mapping to idiomatic forms per language
  - `setup_telemetry` → Python `setup_telemetry()`, TS `setupTelemetry()`, Go `Setup()`, Rust `setup()`, C# `Telemetry.Setup()`
- **Config env vars**: All `UNDEF_*` and `OTEL_*` variables that must be recognized
- **Error types**: `TelemetryError`, `ConfigurationError`, `EventSchemaError`
- **Event schema rules**: Segment regex, min/max segments, naming conventions
- **Required behaviors**: Graceful OTel degradation, idempotent init, W3C propagation support
- **Policy types**: Sampling, queue/backpressure, exporter/resilience, cardinality, PII

### What the spec does NOT define

- Internal module structure (each language organizes idiomatically)
- Logging library choice (structlog, pino, slog, tracing, etc.)
- Type system details (generics, error handling patterns)
- Test framework or tooling

### Spec format sketch

```yaml
version: "0.4"
api:
  core:
    - name: setup_telemetry
      category: lifecycle
      required: true
    - name: shutdown_telemetry
      category: lifecycle
      required: true
  logging:
    - name: get_logger
      category: factory
      required: true
    - name: bind_context
      category: context
      required: true
    - name: unbind_context
      category: context
      required: true
    - name: clear_context
      category: context
      required: true
  tracing:
    - name: get_tracer
      category: factory
      required: true
    - name: trace
      category: decorator
      required: true
      note: "decorator/wrapper/macro — idiomatic per language"
    - name: extract_w3c_context
      category: propagation
      required: true
    - name: bind_propagation_context
      category: propagation
      required: true
  metrics:
    - name: counter
      required: true
    - name: gauge
      required: true
    - name: histogram
      required: true
  # ... remaining categories: sampling, backpressure, resilience,
  #     cardinality, pii, health, schema, slo, runtime

naming_conventions:
  python: snake_case
  typescript: camelCase
  go: PascalCase (exported)
  rust: snake_case
  csharp: PascalCase

config_env_vars:
  - prefix: UNDEF_TELEMETRY_
    keys: [SERVICE_NAME, ENVIRONMENT, VERSION, REQUIRED_KEYS, STRICT_SCHEMA]
  - prefix: UNDEF_LOG_
    keys: [LEVEL, FORMAT, CALLER_INFO, SANITIZE_FIELDS]
  - prefix: UNDEF_TRACE_
    keys: [ENABLED, SAMPLE_RATE]
  - prefix: UNDEF_METRICS_
    keys: [ENABLED]
  # OTEL_* vars are pass-through to OTel SDK

required_behaviors:
  - id: graceful_degradation
    description: "OTel is optional. When unavailable, use no-op tracers/meters silently."
  - id: idempotent_init
    description: "setup() can be called multiple times safely."
  - id: w3c_propagation
    description: "Must extract and inject W3C traceparent/tracestate headers."
  - id: async_context_safety
    description: "Per-request state must be isolated across concurrent tasks."
```

### Conformance validation

`spec/validate_conformance.py` reads the spec and checks each language:

- **Python**: Introspects `__all__` from `undef.telemetry.__init__`
- **TypeScript**: Parses `index.ts` exports
- **Go**: Parses exported symbols via `go doc` or AST
- **Rust**: Parses `pub` items from `lib.rs`
- **C#**: Parses public API from compiled assembly or source

CI runs this on every PR. Failures block merge.

## Versioning

### Current → New

Currently `VERSION` contains `0.3.18` (full semver) and both Python and TypeScript use it directly.

New scheme:
- `VERSION` contains major.minor only: `0.4`
- Each language tracks its own patch version in its native config:
  - **Python**: `pyproject.toml` version becomes dynamic, assembled from `VERSION` + `PATCH` file or build-time logic
  - **TypeScript**: `package.json` `"version": "0.4.0"`, CI validates major.minor matches `VERSION`
  - **Go**: Git tags `go/v0.4.0`, `go/v0.4.1`, etc.
  - **Rust**: `Cargo.toml` `version = "0.4.0"`, CI validates
  - **C#**: `.csproj` `<Version>0.4.0</Version>`, CI validates

### Version sync CI check

`scripts/check_version_sync.py` (or added to `ci-spec.yml`):
1. Reads `VERSION` for the canonical major.minor
2. Reads each language's version from its config
3. Asserts all share the same major.minor
4. Fails CI on mismatch

### Release workflow

Evolve from single `v*` tag to per-language tags:
- `py-v0.4.1` → triggers Python publish
- `ts-v0.4.2` → triggers TypeScript publish
- `go-v0.4.0` → triggers Go module tag
- `rs-v0.4.0` → triggers crates.io publish
- `cs-v0.4.0` → triggers NuGet publish

A `v0.4.0` tag (no language prefix) could trigger all languages simultaneously for coordinated releases.

## Cross-Language E2E Tests

### Current state

`tests/e2e/test_cross_language_trace_e2e.py` already validates Python↔TypeScript trace propagation through OpenObserve. The pattern: Python pytest orchestrates subprocesses, W3C traceparent links spans, OpenObserve query confirms shared trace_id.

### Extended pattern

Promote cross-language E2E tests to `e2e/` at the repo root. Each new language gets:

1. **A test backend** (like `cross_language_server.py`) — a minimal HTTP server that accepts a request with `traceparent`, creates a span, and exports to OTLP
2. **A test client** — sends a request with a generated `traceparent`
3. **Test orchestration** — pytest spawns both, queries OpenObserve for linked spans

The matrix grows: Python↔TypeScript, Python↔Go, TypeScript↔Rust, Go↔C#, etc. Not all pairs are needed — testing each language as both client and server against one other language provides sufficient coverage.

### Minimum E2E coverage per language

Each language must demonstrate:
1. **Trace export**: Emit a span that appears in OpenObserve
2. **W3C propagation**: Accept incoming `traceparent`, produce a child span with same trace_id
3. **Cross-language linkage**: At least one test where this language's span links to another language's span

## CI Architecture

### Per-language workflows with path filters

```yaml
# ci-go.yml
on:
  push:
    paths: ['go/**', 'spec/**', 'VERSION']
  pull_request:
    paths: ['go/**', 'spec/**', 'VERSION']
```

Each language workflow includes:
- Lint, format, type-check (idiomatic per language)
- Unit tests with coverage enforcement
- Spec conformance check
- Version sync check

### Shared workflows

- `ci-spec.yml`: Runs `validate_conformance.py` across all languages, version sync
- `ci-cross-language.yml`: Cross-language E2E tests (dispatch + schedule, requires OpenObserve)

### Quality gates per language

| Gate | Python | TypeScript | Go | Rust | C# |
|------|--------|------------|-----|------|-----|
| Coverage | 100% branch | 100% branch | TBD | TBD | TBD |
| Mutation | 100% kill | 100% kill | TBD | TBD | TBD |
| Lint | ruff | eslint | golangci-lint | clippy | dotnet format |
| Types | mypy strict | tsc strict | native | native | nullable enabled |
| Max LOC/file | 500 | 500 | 500 | 500 | 500 |
| SPDX headers | required | required | required | required | required |

New languages start with reasonable coverage targets (e.g. 80% branch coverage, no mutation gate initially) and ratchet up toward the Python/TypeScript standard over time.

### License

All languages use Apache-2.0.

## Language-Specific Notes

### Go (`go/`)

- Module path: `github.com/undef-games/undef-telemetry/go`
- Use `slog` for structured logging (stdlib, Go 1.21+)
- OTel Go SDK for tracing/metrics, with no-op fallback
- `context.Context` for async safety (idiomatic Go)
- API naming: `telemetry.Setup()`, `telemetry.GetLogger()`, `telemetry.Counter()`

### Rust (`rust/`)

- Crate name: `undef-telemetry`
- Use `tracing` crate for structured logging + spans
- OTel Rust SDK (`opentelemetry` crate) for export, with no-op fallback
- Feature flags: `otel` (mirrors Python extras)
- API naming: `telemetry::setup()`, `telemetry::get_logger()`, `telemetry::counter()`

### C# (`csharp/`)

- Package: `Undef.Telemetry` on NuGet
- Use `Microsoft.Extensions.Logging` + `System.Diagnostics.Activity` for tracing
- OTel .NET SDK optional, with no-op fallback
- `AsyncLocal<T>` for context propagation
- API naming: `Telemetry.Setup()`, `Telemetry.GetLogger()`, `Telemetry.Counter()`

## Migration Plan (High Level)

### Phase 1: Spec infrastructure (no breaking changes)
1. Create `spec/telemetry-api.yaml`
2. Create `spec/validate_conformance.py` — validate Python + TypeScript
3. Add `ci-spec.yml`
4. Transition `VERSION` from `0.3.18` → `0.4` (major.minor only)
5. Update Python/TypeScript version reading to handle major.minor + patch

### Phase 2: Promote E2E tests
6. Move `tests/e2e/` → `e2e/` (update imports, `_REPO_ROOT` paths)
7. Update `ci.yml` E2E jobs to reference new location

### Phase 3: Add languages (one at a time)
8. Go implementation + `ci-go.yml`
9. Rust implementation + `ci-rust.yml`
10. C# implementation + `ci-csharp.yml`

### Phase 4: Release workflow evolution
11. Update `release.yml` to support per-language tags
12. Add `scripts/check_version_sync.py` to CI

## Verification

- `spec/validate_conformance.py` passes for Python and TypeScript before adding new languages
- Cross-language E2E tests pass after promoting to `e2e/`
- Version sync check passes with new `VERSION` format
- Each new language passes spec conformance + at least one cross-language E2E test before merge
