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
uv run python scripts/check_max_loc.py --max-lines 500   # No file may exceed 500 lines
uv run python scripts/check_spdx_headers.py              # All source files need SPDX headers
uv run python scripts/run_mutation_gate.py --python-version 3.11 --retries 1  # 100% mutation kill required
```

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

- **100% branch coverage** is enforced — every new code path needs test coverage.
- **100% mutation kill score** is required in CI — tests must detect behavioural changes.
- **500 LOC max per file** — split files before they exceed this limit.
- **SPDX license headers required** in all source files (Apache-2.0 for this repo)
- **mypy strict mode** — no `Any`, no untyped functions, full annotations required.
- Pytest markers: `otel`, `integration`, `e2e`, `tooling`, `memray`, `slow` — tag tests appropriately.

## Architecture

```
src/undef/telemetry/
├── __init__.py          # Public API facade — only import from here in consumers
├── setup.py             # Idempotent setup()/teardown() with threading.Lock
├── config.py            # Pydantic models, all config via env vars (UNDEF_* / OTEL_*)
├── logger/
│   ├── core.py          # structlog pipeline: configure_logging(), build_handlers()
│   ├── context.py       # contextvars: bind_request_context(), bind_session_context()
│   └── processors.py    # structlog processors: schema validation, sanitize, merge ctx
├── tracing/
│   ├── provider.py      # OTel TracerProvider or no-op fallback
│   ├── context.py       # contextvars: trace_id, span_id
│   └── decorators.py    # @trace async decorator
├── metrics/
│   ├── provider.py      # OTel MeterProvider or no-op fallback
│   └── instruments.py   # Counter, Gauge, Histogram wrappers
├── asgi/
│   ├── middleware.py    # TelemetryMiddleware — binds request context per HTTP/WS request
│   └── websocket.py     # WebSocket context helpers
└── schema/
    └── events.py        # Event name validation, required-key enforcement
```

**Key design patterns:**

- **Graceful degradation**: OTel is optional. When unavailable or unconfigured, no-op tracers/meters are used silently. Never raise on missing OTel.
- **Lock-protected idempotent init**: `setup.py`, `logger/core.py`, and both providers use `threading.Lock` + a sentinel flag to allow safe repeated calls.
- **contextvars for async safety**: All per-request state (trace IDs, session, user) lives in `contextvars` — safe across `await` boundaries and isolated per task.
- **Processor chain**: structlog processors run in order — add standard fields → merge context → enforce schema → sanitize → format (console or JSON).
- **No direct OTel imports at module level** in non-`otel`-extra files — guard all OTel imports with `try/except ImportError`.

## Configuration

All runtime config comes from environment variables, parsed via `TelemetryConfig.from_env()`:

| Prefix | Controls |
|--------|----------|
| `UNDEF_TELEMETRY_*` | Service name, env, version, schema strictness |
| `UNDEF_LOG_*` | Log level, format, caller info, sanitization |
| `UNDEF_TRACE_*` | Tracing enabled, sample rate |
| `UNDEF_METRICS_*` | Metrics enabled |
| `OTEL_EXPORTER_OTLP_*` | OTLP endpoint/headers (standard OTel env vars) |

## Testing Conventions

- Tests live in `tests/` mirroring the `src/undef/telemetry/` structure.
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
- `VERSION` contains major.minor only (e.g. `0.3`); each language tracks patch independently.
- `e2e/` — cross-language E2E tests.
- Language directories: `typescript/` (implemented), `go/`, `rust/`, `csharp/` (planned) — each self-contained with own build config.
- Python stays at repo root (`src/`, `pyproject.toml`, `tests/`).
