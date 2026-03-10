# undef-telemetry

Unified telemetry package for the Undef ecosystem.

## API

```python
from undef.telemetry import (
    setup_telemetry,
    get_logger, logger,
    trace, tracer, get_tracer,
    counter, gauge, histogram, get_meter,
    TelemetryMiddleware,
)
```

## Quick Start

```python
from undef.telemetry import setup_telemetry, shutdown_telemetry, get_logger

setup_telemetry()
log = get_logger(__name__)
log.info("app.start.ok", request_id="req-1")
shutdown_telemetry()
```

## Async Safety

The library uses `contextvars` for runtime context propagation and lock-protected setup for idempotent initialization.

## OpenTelemetry Extras Validation

Install with OTel extras and run OTel-marked tests:

```bash
uv sync --group dev --extra otel
uv run pytest -m otel -q
```

## Environment Variables

- `UNDEF_TELEMETRY_SERVICE_NAME`
- `UNDEF_TELEMETRY_ENV`
- `UNDEF_TELEMETRY_VERSION`
- `UNDEF_TELEMETRY_STRICT_SCHEMA`
- `UNDEF_LOG_LEVEL`
- `UNDEF_LOG_FORMAT`
- `UNDEF_TRACE_ENABLED`
- `UNDEF_METRICS_ENABLED`
- `UNDEF_LOG_CODE_ATTRIBUTES`
- `OTEL_EXPORTER_OTLP_ENDPOINT`
- `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`
- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
- `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`

## Event Naming Rule

Event names are strict: `domain.action.status` with exactly 3 segments.
If you build names dynamically, use `undef.telemetry.event_name(domain, action, status)`.

```python
from undef.telemetry import event_name, get_logger

log = get_logger(__name__)
log.info(event_name("auth", "login", "success"), user_id="u-123")
log.info(event_name("auth", "login", "failed"), reason="bad_password")
```

## Quality

```bash
uv sync --group dev
uvx reuse lint
uv run codespell
uv run python scripts/check_max_loc.py --max-lines 500
uv run python scripts/check_spdx_headers.py
uv run python scripts/check_event_literals.py
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run ty check src tests
uv run bandit -r src -ll
uv run python scripts/run_pytest_gate.py
uv sync --group dev --extra otel
uv run python scripts/run_pytest_gate.py -m otel -q
# Optional full E2E against live OpenObserve
export OPENOBSERVE_URL=http://localhost:5080/api/default
export OPENOBSERVE_USER=tim@provide.io
export OPENOBSERVE_PASSWORD=password
uv run python scripts/run_pytest_gate.py -m e2e --no-cov -q
# Property + mutation quality gates
uv run python scripts/run_pytest_gate.py -k hypothesis -q --no-cov
uv run python scripts/run_mutation_gate.py --python-version 3.11 --retries 1 --min-mutation-score 100
```

> Marker-specific runs (e.g., `-m otel`, `-m e2e`, `-k hypothesis`) already pass `--no-cov`; the strict 100% coverage gate only applies to the baseline `uv run python scripts/run_pytest_gate.py` invocation.

## OpenObserve Verification

Set the OpenObserve credentials and run the e2e suite to prove all signals arrive in the backend:

```bash
export OPENOBSERVE_URL=http://localhost:5080/api/default
export OPENOBSERVE_USER=tim@provide.io
export OPENOBSERVE_PASSWORD=password
uv run --group dev --extra otel python examples/openobserve/01_emit_all_signals.py
uv run --group dev --extra otel python examples/openobserve/02_verify_ingestion.py
uv run python scripts/run_pytest_gate.py -m e2e --no-cov -q
```

Once the run finishes, open `http://localhost:5080/web/streams?org_identifier=default` and search for:

- `default` traces where `operation_name` is `e2e.openobserve.span`
- logs tagged with `e2e.openobserve.log`
- metric stream names like `e2e.requests.<timestamp>`

Refreshing the UI should show the incremental doc counts that the examples and tests emit.

`run_mutation_gate.py` automatically injects a local `setproctitle` compatibility shim for mutmut subprocesses.

## Python SPDX Header Convention

Every Python file uses this exact first-block structure:

```python
#!/usr/bin/env python3  # optional
# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#
```

Normalization and enforcement:

```bash
uv run python scripts/normalize_spdx_headers.py
uv run python scripts/check_spdx_headers.py
```

## Docs

- [Operations Runbook](docs/OPERATIONS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Telemetry Conventions](docs/CONVENTIONS.md)
- [Compliance Notes](docs/COMPLIANCE.md)
- [Release Runbook](docs/RELEASE.md)
- [Examples](examples/README.md)
