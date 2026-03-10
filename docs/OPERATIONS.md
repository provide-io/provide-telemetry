# Operations Runbook

## Runtime Defaults

- Python: 3.11+
- Log format default: `console`
- Event schema validation: enabled (`UNDEF_TELEMETRY_STRICT_EVENT_NAME=true` by default)
- Strict schema mode: off by default (`UNDEF_TELEMETRY_STRICT_SCHEMA=false`)

See also: [`docs/PRODUCTION_PROFILES.md`](PRODUCTION_PROFILES.md) for strict/compat/high-throughput presets.

## Core Environment Variables

- `UNDEF_TELEMETRY_SERVICE_NAME`
- `UNDEF_TELEMETRY_ENV`
- `UNDEF_TELEMETRY_VERSION`
- `UNDEF_TELEMETRY_STRICT_SCHEMA`
- `UNDEF_TELEMETRY_STRICT_EVENT_NAME`
- `UNDEF_TELEMETRY_REQUIRED_KEYS`
- `UNDEF_LOG_LEVEL`
- `UNDEF_LOG_FORMAT`
- `UNDEF_LOG_INCLUDE_TIMESTAMP`
- `UNDEF_LOG_INCLUDE_CALLER`
- `UNDEF_LOG_CODE_ATTRIBUTES`
- `UNDEF_LOG_SANITIZE`
- `UNDEF_TRACE_ENABLED`
- `UNDEF_TRACE_SAMPLE_RATE`
- `UNDEF_METRICS_ENABLED`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`
- `OTEL_EXPORTER_OTLP_LOGS_HEADERS`
- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
- `OTEL_EXPORTER_OTLP_TRACES_HEADERS`
- `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`
- `OTEL_EXPORTER_OTLP_METRICS_HEADERS`
- `UNDEF_EXPORTER_LOGS_RETRIES`
- `UNDEF_EXPORTER_TRACES_RETRIES`
- `UNDEF_EXPORTER_METRICS_RETRIES`
- `UNDEF_EXPORTER_LOGS_BACKOFF_SECONDS`
- `UNDEF_EXPORTER_TRACES_BACKOFF_SECONDS`
- `UNDEF_EXPORTER_METRICS_BACKOFF_SECONDS`
- `UNDEF_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP`
- `UNDEF_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP`
- `UNDEF_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP`
- `OPENOBSERVE_URL`
- `OPENOBSERVE_USER`
- `OPENOBSERVE_PASSWORD`

## Event Naming Policy

Canonical naming rules and examples live in [`docs/CONVENTIONS.md`](CONVENTIONS.md).
Operationally, keep strict validation enabled unless you are in an explicit migration window.

## Failure Behavior

- Missing OTel dependencies: tracing falls back to no-op tracer objects and metrics use in-process fallback wrappers.
- Invalid event names with strict event mode enabled: raises `EventSchemaError`.
- Missing required keys: raises `EventSchemaError` only when `UNDEF_TELEMETRY_STRICT_SCHEMA=true`.
- Async services: keep exporter retries/backoff at zero (default). Non-zero values can block request handlers; runtime guard forces fail-fast unless explicit `*_ALLOW_BLOCKING_EVENT_LOOP=true`.

## Lifecycle

- Call `setup_telemetry()` once during process startup.
- Call `shutdown_telemetry()` during graceful shutdown to flush providers.
- `setup_telemetry()` and `shutdown_telemetry()` are lock-serialized; concurrent calls are safe.
- After `shutdown_telemetry()`, a subsequent `setup_telemetry()` call performs a full reinitialization (including logging providers).
- `update_runtime_config()` and `reload_runtime_from_env()` return the applied runtime snapshot, not a caller-owned mutable config reference.

## Local Health Check

```bash
uv sync --group dev
uv run python scripts/check_max_loc.py --max-lines 500
uv run python scripts/check_event_literals.py
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run ty check src tests
uv run bandit -r src -ll
uv run python scripts/run_pytest_gate.py
uv sync --group dev --extra otel
uv run python scripts/run_pytest_gate.py -m otel -q
# Optional full e2e (requires live OpenObserve)
uv run python scripts/run_pytest_gate.py -m e2e --no-cov -q
# Optional fuzz/property run
uv run python scripts/run_pytest_gate.py tests/fuzz tests/property --no-cov
# Optional mutation pass (can take time)
uv run python scripts/run_mutation_gate.py --python-version 3.11 --retries 1 --min-mutation-score 100
# Optional performance smoke (report-only by default)
uv run python scripts/run_performance_smoke.py --iterations 300000
```

Note: `run_mutation_gate.py` injects a no-op `setproctitle` shim for mutmut subprocesses to avoid known segfault behavior on some hosts.
Marker-specific runs (`-m otel`, `-m e2e`, `tests/fuzz`/`tests/property`, etc.) should continue to pass `--no-cov` because the strict 100% coverage gate applies only to the default `pytest` run.

## Docs Quality

The `docs-quality` CI job is a required gate. Run the same checks locally:

```bash
uv sync --group dev
uv run python scripts/check_docs_accuracy.py
uv run python scripts/run_pytest_gate.py tests/docs tests/tooling/test_check_docs_accuracy.py --no-cov -q
```

## Act / Docker-in-Docker Quality Runs

When acting as a local runner on macOS with `colima`, prefer `${HOME}`-based socket paths:

```bash
export DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"
act -W .github/workflows/ci.yml workflow_dispatch -j quality \
  --container-architecture linux/amd64 \
  --container-daemon-socket "${DOCKER_HOST}" \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

For jobs that do not need Docker inside the job container (for example `docs-quality`), disable
daemon socket bind-mount to avoid macOS/Colima mount issues:

```bash
export DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"
act -W .github/workflows/ci.yml pull_request -j docs-quality \
  --container-architecture linux/amd64 \
  --container-daemon-socket -
```

Add the above to `.actrc` for quieter commands and document any socket/mount errors.

## OpenObserve Validation

After running `uv run python scripts/run_pytest_gate.py -m e2e --no-cov -q` with the `OPENOBSERVE_*`
env vars in place, verify telemetry landed:

1. Browse `http://localhost:5080/web/streams?org_identifier=default` and look for `undef-telemetry` streams.
2. Search for `e2e.openobserve.span` or the metric stream name from `tests/e2e/test_openobserve_e2e.py`.
3. Rerun the examples in `examples/openobserve/` if nothing appears immediately, then refresh the UI.
