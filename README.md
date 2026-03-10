# undef-telemetry

Unified telemetry package for the Undef ecosystem.

## Install

```bash
pip install undef-telemetry
```

Optional extras:

```bash
pip install "undef-telemetry[otel]"
```

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
- `UNDEF_EXPORTER_LOGS_TIMEOUT_SECONDS`
- `UNDEF_EXPORTER_TRACES_TIMEOUT_SECONDS`
- `UNDEF_EXPORTER_METRICS_TIMEOUT_SECONDS`

## Event Naming Rule

Event names are strict: `domain.action.status` with exactly 3 segments.
If you build names dynamically, use `undef.telemetry.event_name(domain, action, status)`.

```python
from undef.telemetry import event_name, get_logger

log = get_logger(__name__)
log.info(event_name("auth", "login", "success"), user_id="u-123")
log.info(event_name("auth", "login", "failed"), reason="bad_password")
```

## OpenObserve Quick Verification

```bash
export OPENOBSERVE_URL=http://localhost:5080/api/default
export OPENOBSERVE_USER=user@example.com
export OPENOBSERVE_PASSWORD=password
export OPENOBSERVE_REQUIRED_SIGNALS=logs
uv run --group dev --extra otel python examples/openobserve/01_emit_all_signals.py
uv run --group dev --extra otel python examples/openobserve/02_verify_ingestion.py
```

Set `OPENOBSERVE_REQUIRED_SIGNALS=logs,metrics,traces` when your runtime has OTel extras and you want hard all-signal verification.

Script references:

- [Emit all signals example](https://github.com/undef-games/undef-telemetry/blob/main/examples/openobserve/01_emit_all_signals.py)
- [Verify ingestion example](https://github.com/undef-games/undef-telemetry/blob/main/examples/openobserve/02_verify_ingestion.py)

## Quality Guarantees

- Baseline test gate runs at `100%` branch coverage (`--cov-branch`).
- Mutation gate enforces `--min-mutation-score 100`.
- Mutation policy is pinned in `.ci/pymutant-profiles.json` (`min_score: 1.0`, `max_drop_from_baseline: 0.0`) with baseline score in `.ci/pymutant-policy-baseline.json`.
- CI validates linting, typing, security, compliance, examples, and integration slices.
- Async-safe default exporter policy keeps retries/backoff at zero; non-zero async retry behavior is opt-in via `UNDEF_EXPORTER_*_ALLOW_BLOCKING_EVENT_LOOP=true`.
- Exporter timeout settings are enforced both in OTLP exporter construction and per-attempt resilience execution bounds.

## Documentation Ownership

- README: onboarding and first successful local/backend verification.
- Operations: full CQ matrix, troubleshooting, and environment operations.
- Conventions: event/schema rules and naming standards.
- Release: packaging/tagging/publishing workflow.

## Docs

- [Operations Runbook](https://github.com/undef-games/undef-telemetry/blob/main/docs/OPERATIONS.md)
- [Production Profiles](https://github.com/undef-games/undef-telemetry/blob/main/docs/PRODUCTION_PROFILES.md)
- [Architecture](https://github.com/undef-games/undef-telemetry/blob/main/docs/ARCHITECTURE.md)
- [Telemetry Conventions](https://github.com/undef-games/undef-telemetry/blob/main/docs/CONVENTIONS.md)
- [Compliance Notes](https://github.com/undef-games/undef-telemetry/blob/main/docs/COMPLIANCE.md)
- [Release Runbook](https://github.com/undef-games/undef-telemetry/blob/main/docs/RELEASE.md)
- [Examples](https://github.com/undef-games/undef-telemetry/blob/main/examples/README.md)
- [Main CI Workflow](https://github.com/undef-games/undef-telemetry/blob/main/.github/workflows/ci.yml)
- [Release Workflow](https://github.com/undef-games/undef-telemetry/blob/main/.github/workflows/release.yml)
