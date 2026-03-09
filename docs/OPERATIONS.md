# Operations Runbook

## Runtime Defaults

- Python: 3.11+
- Log format default: `console`
- Event schema validation: enabled (`UNDEF_TELEMETRY_STRICT_EVENT_NAME=true` by default)
- Strict schema mode: off by default (`UNDEF_TELEMETRY_STRICT_SCHEMA=false`)

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
- `OPENOBSERVE_URL`
- `OPENOBSERVE_USER`
- `OPENOBSERVE_PASSWORD`

## Event Naming Policy

Use `domain.action.status`, all lowercase, underscores allowed.

Examples:

- `auth.login.success`
- `session.connect.failed`
- `ws.message.received`

## Failure Behavior

- Missing OTel dependencies: library falls back to no-op tracing/metrics wrappers.
- Invalid event names with strict event mode enabled: raises `EventSchemaError`.
- Missing required keys: raises `EventSchemaError`.

## Lifecycle

- Call `setup_telemetry()` once during process startup.
- Call `shutdown_telemetry()` during graceful shutdown to flush providers.

## Local Health Check

```bash
uv sync --group dev
uv run python scripts/check_max_loc.py --max-lines 500
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
uv run python scripts/run_mutation_gate.py --python-version 3.11 --retries 1
```

Note: `run_mutation_gate.py` injects a no-op `setproctitle` shim for mutmut subprocesses to avoid known segfault behavior on some hosts.
Marker-specific runs (`-m otel`, `-m e2e`, `tests/fuzz`/`tests/property`, etc.) should continue to pass `--no-cov` because the strict 100% coverage gate applies only to the default `pytest` run.

## Act / Docker-in-Docker Quality Runs

When acting as a local runner reuse the host docker daemon socket. On macOS with `colima`:

```bash
export DOCKER_HOST=unix:///REDACTED_ABS_PATH
act -W .github/workflows/ci.yml workflow_dispatch -j quality \
  --container-architecture linux/amd64 \
  --container-daemon-socket "${DOCKER_HOST}" \
  -P ubuntu-latest=catthehacker/ubuntu:act-latest
```

Add the above to `.actrc` for quieter commands and document any socket/mount errors.

## OpenObserve Validation

After running `uv run python scripts/run_pytest_gate.py -m e2e --no-cov -q` with the `OPENOBSERVE_*`
env vars in place, verify telemetry landed:

1. Browse `http://localhost:5080/web/streams?org_identifier=default` and look for `undef-telemetry` streams.
2. Search for `e2e.openobserve.span` or the metric stream name from `tests/e2e/test_openobserve_e2e.py`.
3. Rerun the examples in `examples/openobserve/` if nothing appears immediately, then refresh the UI.
