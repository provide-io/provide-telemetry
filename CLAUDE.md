# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Setup:**
```bash
uv sync --group dev                        # Base dev dependencies
uv sync --group dev --extra otel           # Include OpenTelemetry extras
```

**Run tests:**
```bash
uv run python scripts/run_pytest_gate.py                             # Core suite (100% coverage enforced)
uv run python scripts/run_pytest_gate.py -k "test_name"             # Single test
uv run python scripts/run_pytest_gate.py --no-cov -q -k "test_name" # Single test, no coverage
uv run python scripts/run_pytest_gate.py -m otel --no-cov -q        # OTel-specific tests
uv run python scripts/run_pytest_gate.py -m e2e --no-cov -q         # E2E (requires live OpenObserve)
uv run python scripts/run_pytest_gate.py -k hypothesis --no-cov -q  # Property-based tests
```

**Lint/type-check:**
```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run bandit -r src -ll
uv run codespell
```

**Custom gates:**
```bash
uv run python scripts/check_max_loc.py --max-lines 777   # No file may exceed 777 lines
uv run python scripts/check_spdx_headers.py              # All source files need SPDX headers
uv run python scripts/run_mutation_gate.py --python-version 3.11 --retries 1  # 100% mutation kill required
```

> **Run mutation and fuzz gates ONE AT A TIME on a workstation.** Each one
> saturates every core by default and they are individually memory-hungry:
> Stryker forks ~20 node workers, `pytest -n 8` forks 8 interpreters, `go test
> -fuzz` runs GOMAXPROCS workers at ~100k exec/s, and cargo-mutants rebuilds the
> crate per mutant. Two of these at once will OOM a 26 GB machine. Bound them:
>
> ```bash
> uv run python scripts/run_mutation_gate.py --max-children 2   # not the 1/3-CPU default
> npx stryker run --concurrency 2
> go test -p 2 ./...                                            # seeds only; add -fuzz deliberately
> go test -run FuzzX -fuzz FuzzX -fuzztime 30s -parallel 2 .
> cargo mutants --in-place --all-features --shard 1/8            # shard rather than run whole
> #   --in-place is required, not an optimisation: three Rust tests read
> #   spec/*.yaml through concat!(env!("CARGO_MANIFEST_DIR"), "/../spec/…"),
> #   which resolves at compile time. In cargo-mutants' default scratch copy
> #   that path does not exist, cargo test fails in the unmutated tree, and the
> #   run tests zero mutants. --in-place also rejects -j; bound fan-out with
> #   CARGO_BUILD_JOBS=1 and NEXTEST_TEST_THREADS=1 instead.
> #   ...and if you do run it out-of-place for some reason, point TMPDIR at real
> #   disk: cargo-mutants copies the crate and builds it per mutant, which
> #   exhausts a 14G /tmp tmpfs and dies with EDQUOT.
> #   TMPDIR=~/.cache/cargo-mutants-tmp cargo mutants ...
> uv run pytest -p no:xdist ...                                 # serial when running alongside anything
> ```
>
> CI runs them as separate jobs on separate runners, which is why the workflow
> passes no concurrency caps — do not copy those invocations locally verbatim.

**Memory profiling:**
```bash
make memray                                                # Run all memray stress tests
make memray-flamegraph                                     # Generate HTML flamegraphs
make memray-analyze                                        # Run tracemalloc audit
make memray-baseline                                       # Update regression baselines
make perf-smoke                                            # Run performance timing benchmarks
uv run pytest tests/memray/ -m memray -v --no-cov          # Run memray regression tests
uv run python scripts/memray/memray_analysis.py            # Generate analysis report + flamegraphs
```

## Quality Constraints

- **100% coverage** is enforced for Python and TypeScript (branch) and Go (statement, per OS).
  C# is gated by `ci/check_csharp_coverage.py` at 100% line / 98% branch.
- **Rust has a coverage gate too** — `ci-rust.yml` runs `cargo llvm-cov` with
  `--fail-under-functions 100`, so every function must be exercised. `cargo test`
  passing tells you nothing about it: a new `match` arm or error path that no test
  reaches compiles, tests green, and fails only in CI. Run it before pushing Rust:
  ```bash
  cargo llvm-cov --all-targets --all-features \
    --ignore-filename-regex '/rustlib/src/rust/library/|/\.rustup/|/toolchains/' \
    --fail-uncovered-lines 0 --fail-under-functions 100
  ```
- **100% mutation kill score** is enforced, not merely targeted, in Python, Go and Rust;
  TypeScript and C# gate on a score floor:
  - **Python** — `scripts/run_mutation_gate.py`. Note `_is_clean()` requires *zero*
    survivors, timeouts, suspicious and no-tests results; `--min-mutation-score` is an
    additional floor, not the bar. A run at 99% still fails.
  - **Go** — gremlins over six surfaces: the root package, the four `internal/`
    packages (`piicore`, `fingerprintcore`, `schemacore`, `levelcore`), and the `otel`
    module — each run through `scripts/run_gremlins_gate.sh`. The `internal/` steps
    target `.` rather than the package itself, because gremlins builds its coverage
    profile from the tests of the target path and almost everything exercising those
    packages lives in the root package; `--coverpkg` attributes that coverage onto the
    internal package and the `--exclude-files` list narrows what is mutated back down
    to it. The wrapper is what enforces the gate:
    gremlins' own `--threshold-efficacy` / `--threshold-mcover` flags do **not** fail
    the run — v0.6.0 exits 0 even when asked for an impossible 101% — so the flags are
    kept only for the numbers they print. The wrapper fails on a surviving, uncovered
    or timed-out mutant, and on a run that printed no summary at all (a crashed run
    would otherwise read as a pass). Locally the `otel` module needs
    `GOTOOLCHAIN=go1.26.1`: gremlins copies the module to a temp dir where its
    `replace => ../` and Go's toolchain auto-switching disagree.
  - **Rust** — `cargo mutants` across 8 CI shards. No threshold flag is passed because
    cargo-mutants exits non-zero on any surviving mutant by default.
  - **TypeScript** — Stryker, run twice (`stryker.config.mjs` then
    `stryker.otel.config.mjs`, via `npm run test:mutation`), with `thresholds.break` at
    95 and 80 respectively. No wrapper enforces zero survivors, so a run fails only below
    those scores. Its surface is also *not* whole: see the `mutate:` exclusion list,
    where each excluded file carries the reason inline.
  - **C#** — Stryker.NET with a score floor, not 100%: `break` in
    `csharp/stryker-config.json` (currently 85), with the reasoning recorded there.
- `# pragma: no mutate` only takes effect on a **whole single-line statement**. mutmut
  ignores it on a continuation line and on an element inside a multi-line dict/list
  literal, and `block` pragmas cannot nest. Beware that `ruff format` can re-wrap a long
  line and silently orphan a working pragma — hoist the value to its own short statement
  (or a module constant) rather than fighting the formatter.
- **777 LOC max per file** — enforced across Python, TypeScript, Go, and Rust via `scripts/check_max_loc.py`. Pre-existing violators are tracked in `.max_loc_allowlist.yaml` with split plans; new files MUST stay under 777 lines.
- **SPDX license headers required** in all source files (Apache-2.0 for this repo)
- **mypy strict mode** — no `Any`, no untyped functions, full annotations required.
- Pytest markers: `otel`, `integration`, `e2e`, `mock_e2e`, `tooling`, `memray`, `slow`, `flaky` — tag tests appropriately.

## Architecture

```
src/provide/telemetry/
├── __init__.py          # Public API facade — only import from here in consumers
├── _lazy.py             # Lazy-import registry backing the facade
├── setup.py             # Idempotent setup_telemetry()/flush/shutdown_telemetry() coordinator
├── _lifecycle.py        # Immutable lifecycle generations + the one lock that publishes them
├── _provider_drain.py   # Bounded provider flush/shutdown calls, per-signal drains
├── config.py            # stdlib @dataclass(slots=True), all config via env vars (PROVIDE_* / OTEL_*)
├── _config_validation.py, _config_prometheus.py  # env parsing / Prometheus settings validation
├── _endpoint.py, _otlp_tls.py, _masking.py       # OTLP endpoint checks, TLS file checks, credential masking
├── _otel.py             # OTel introspection utilities (lazy import helpers)
├── _resource.py         # OTel Resource construction shared by the providers
├── exceptions.py        # TelemetryError, ConfigurationError, ProviderImmutableError
├── health.py            # Self-observability counters and snapshot
├── runtime.py           # Hot-reload API (_runtime_types.py: its value types)
├── _runtime_policies.py # Pushes a config generation's hot policy values into the subsystems
├── levels.py            # Canonical severity ladder and string-to-level converter
├── consent.py           # Consent-level gating (first admission stage)
├── sampling.py          # Per-signal probabilistic sampling
├── backpressure.py      # Bounded queue ticket system
├── pii.py               # PII rule engine with secret detection and nested traversal
├── _secret_patterns_generated.py  # Generated from spec/secret_patterns.yaml — do not edit
├── classification.py    # Data classification engine
├── receipts.py          # Cryptographic redaction receipts
├── _record_marker.py    # Marks a LogRecord this SDK already hardened and sanitized
├── propagation.py       # W3C traceparent/tracestate extraction with size guards
├── resilience.py        # Retry, timeout, circuit breaker, timeout executors
├── resilient_exporter.py # Per-export resilience wrappers for OTel exporters
├── cardinality.py       # TTL-based attribute cardinality guards
├── slo.py               # RED/USE metric helpers
├── headers.py           # Safe ASGI header extraction
├── testing.py           # Opt-in pytest plugin for test isolation (not auto-registered)
├── logger/
│   ├── core.py          # structlog pipeline: configure_logging(), handler build, get_logger()
│   ├── processors.py    # structlog processors: admission, harden_input, fingerprint, schema, sanitize
│   ├── _foreign_records.py # Hardening + PII for stdlib records that bypassed the structlog chain
│   ├── handlers.py      # Stdlib logging handlers used by the pipeline
│   ├── _otel_logs.py    # OTel log-provider wiring
│   ├── sink.py, console.py, _windows_console.py  # Log destination and what it can render
│   ├── context.py       # contextvars: bind_context(), bind_session_context()
│   └── pretty.py        # Pretty ANSI renderer with configurable colors
├── tracing/
│   ├── provider.py      # OTel TracerProvider or no-op fallback
│   ├── context.py, context_runtime.py  # trace_id/span_id helpers, cross-context OTel context
│   ├── span.py          # Block-level span context manager
│   └── decorators.py    # @trace decorator (sync and async)
├── metrics/
│   ├── provider.py      # OTel MeterProvider (OTLP and/or Prometheus readers) or no-op fallback
│   ├── api.py           # counter(), gauge(), histogram()
│   ├── observable.py    # Observable (callback) instruments
│   ├── instruments.py   # Compatibility re-exports
│   ├── fallback.py      # In-process fallback implementations
│   ├── prometheus.py    # Prometheus pull reader, status, Tier 2 handler
│   ├── _prom_listener.py # Tier 3 standalone listener
│   ├── _prom_render.py, _prom_names.py  # Text exposition rendering, name translation
│   └── _health_otlp.py  # PROVIDE_METRICS_HEALTH_OTLP: health series as observable instruments
├── asgi/
│   ├── middleware.py    # TelemetryMiddleware — binds request/session context, baggage extraction
│   └── websocket.py     # WebSocket context helpers
└── schema/
    └── events.py        # Event name validation, required-key enforcement
```

**Key design patterns:**

- **Graceful degradation**: OTel is optional. When unavailable or unconfigured, no-op tracers/meters are used silently. Never raise on missing OTel.
- **Lock-protected idempotent init**: `setup.py` runs under the lifecycle coordinator's lock (`_lifecycle.py`); `logger/core.py` and the tracer/meter providers each use a `threading.Lock` + a sentinel flag to allow safe repeated calls.
- **contextvars for async safety**: All per-request state (trace IDs, session, user) lives in `contextvars` — safe across `await` boundaries and isolated per task.
- **Processor chain** (`logger/core.py`): merge context → logger name → DAS fields → level → timestamp → per-module level filter → admission (`apply_sampling`: consent → sampling → backpressure) → harden input → standard fields → error fingerprint → enforce schema → PII sanitize + receipts → callsite → render (console, pretty or JSON). Admission before payload work follows the canonical stage order in `spec/pipeline_fixtures.yaml`: consent → sampling → backpressure → hardening → pii → receipt → local → backend → health → release.
- **No direct OTel imports at module level** in non-`otel`-extra files — guard all OTel imports with `try/except ImportError`.

## Configuration

All runtime config comes from environment variables, parsed via `TelemetryConfig.from_env()`:

| Prefix | Controls |
|--------|----------|
| `PROVIDE_TELEMETRY_*` | Service name, env, version, schema strictness |
| `PROVIDE_LOG_*` | Log level, format, caller info, sanitization |
| `PROVIDE_TRACE_*` | Tracing enabled, sample rate |
| `PROVIDE_METRICS_*` | Metrics enabled, Prometheus pull (`PROVIDE_METRICS_PROMETHEUS_*`), `PROVIDE_METRICS_HEALTH_OTLP` |
| `PROVIDE_SAMPLING_*`, `PROVIDE_BACKPRESSURE_*`, `PROVIDE_EXPORTER_*` | Per-signal sampling rates, queue sizes, exporter retry/timeout/fail-open |
| `PROVIDE_SECURITY_*`, `PROVIDE_SLO_*`, `PROVIDE_CONSENT_LEVEL` | Input hardening limits, RED/USE metrics, consent level |
| `OTEL_EXPORTER_OTLP_*` | OTLP endpoint/headers (standard OTel env vars) |
| `OTEL_METRICS_EXPORTER`, `OTEL_EXPORTER_PROMETHEUS_*` | Metric reader selection, Prometheus listener host/port |

## Testing Conventions

- Tests live in `tests/`, grouped by subsystem (`tests/logger/`, `tests/pii/`, `tests/metrics/`, ...).
- `asyncio_mode = "auto"` — async test functions work without decorators.
- Use `importlib.reload()` to reset module-level singletons between tests (see existing tests for the pattern).
- OTel-dependent tests must use `@pytest.mark.otel` and import OTel inside the test or fixture.
- E2E tests require `OPENOBSERVE_URL`, `OPENOBSERVE_USER`, `OPENOBSERVE_PASSWORD` env vars.
- Memray stress tests live in `tests/memray/` with baselines in `tests/memray/baselines.json`.
- Memray tests are excluded from default runs (`-m "not memray"`); run with `make memray-baseline`.

## Polyglot Structure

- `spec/telemetry-api.yaml` — canonical API surface definition; all languages validate against it.
- `spec/validate_conformance.py` — checks language exports against spec.
- `scripts/check_version_sync.py` — ensures all languages share major.minor from `VERSION`.
- `VERSION` holds the canonical full version (currently `0.10.1`); only its major.minor is
  compared across languages, so each language tracks its own patch and they legitimately drift.
- `e2e/` — cross-language E2E tests.
- Language directories: `typescript/`, `go/`, `rust/`, `csharp/` — each self-contained with own build config.
- Python stays at repo root (`src/`, `pyproject.toml`, `tests/`).
- C# (`csharp/`): `Provide.Telemetry` core package + `Provide.Telemetry.OpenTelemetry` OTLP backend,
  xUnit tests under `csharp/tests/`, Stryker mutation config in `csharp/stryker-config.json`.
  Run tests with `dotnet test` from `csharp/`.
