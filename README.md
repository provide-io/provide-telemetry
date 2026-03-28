# Undef Telemetry

Unified telemetry library for structured logging, distributed tracing, and metrics across Python and TypeScript. Graceful OTel degradation — works without OpenTelemetry installed, activates full export when OTel SDK is present.

[![1. 🐍 CI — Python](https://github.com/undef-games/undef-telemetry/actions/workflows/ci-python.yml/badge.svg)](https://github.com/undef-games/undef-telemetry/actions/workflows/ci-python.yml)
[![2. 🟦 CI — TypeScript](https://github.com/undef-games/undef-telemetry/actions/workflows/ci-typescript.yml/badge.svg)](https://github.com/undef-games/undef-telemetry/actions/workflows/ci-typescript.yml)
[![5. 🔒 CodeQL](https://github.com/undef-games/undef-telemetry/actions/workflows/codeql.yml/badge.svg)](https://github.com/undef-games/undef-telemetry/actions/workflows/codeql.yml)

## Install

**Python:**

```bash
pip install undef-telemetry              # core (structlog)
pip install "undef-telemetry[otel]"      # + OpenTelemetry export
```

**TypeScript:**

```bash
npm install @undef/telemetry             # core (pino + @opentelemetry/api)
```

## Quick Start

**Python:**

```python
from undef.telemetry import setup_telemetry, shutdown_telemetry, get_logger

setup_telemetry()
log = get_logger(__name__)
log.info("app.start.ok", request_id="req-1")
shutdown_telemetry()
```

**TypeScript:**

```typescript
import { setupTelemetry, getLogger, shutdownTelemetry } from '@undef/telemetry';

setupTelemetry({ serviceName: 'my-app' });
const log = getLogger('api');
log.info({ event: 'app.start.ok', requestId: 'req-1' });
await shutdownTelemetry();
```

Both languages share the same API surface, event naming conventions, and configuration environment variables.

## Configuration

All runtime config is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `UNDEF_TELEMETRY_SERVICE_NAME` | `undef-service` | Service identity |
| `UNDEF_LOG_LEVEL` | `INFO` | Log level |
| `UNDEF_LOG_FORMAT` | `console` | Renderer: `console`, `json`, or `pretty` |
| `UNDEF_TRACE_ENABLED` | `false` | Enable OTel tracing |
| `UNDEF_METRICS_ENABLED` | `false` | Enable OTel metrics |

See the [Configuration Reference](docs/CONFIGURATION.md) for all 60+ environment variables.

## Event Naming

Event names use 3-5 dot-separated lowercase segments:

```python
# Python
log.info("auth.login.success", user_id="u-123")
log.info(event_name("auth", "login", "failed"), reason="bad_password")
```

```typescript
// TypeScript
log.info({ event: 'auth.login.success', userId: 'u-123' });
```

See [Conventions](docs/CONVENTIONS.md) for full naming rules.

## API Surface

Both languages export equivalent APIs:

| Category | Functions |
|----------|-----------|
| Lifecycle | `setup_telemetry()`, `shutdown_telemetry()` |
| Logging | `get_logger()`, `bind_context()`, `clear_context()` |
| Tracing | `get_tracer()`, `trace` (decorator/wrapper), `extract_w3c_context()` |
| Metrics | `counter()`, `gauge()`, `histogram()` |
| Policies | `set_sampling_policy()`, `set_queue_policy()`, `set_exporter_policy()` |
| Safety | `register_cardinality_limit()`, `register_pii_rule()` |
| Health | `get_health_snapshot()` |
| Runtime | `update_runtime_config()`, `reconfigure_telemetry()` |

Full reference: [Python API](docs/API.md) | [TypeScript API](typescript/README.md)

## Polyglot Architecture

```
undef-telemetry/
  src/undef/telemetry/    # Python package
  typescript/             # TypeScript package (@undef/telemetry)
  spec/                   # Canonical API spec — all languages validate against it
  e2e/                    # Cross-language E2E tests (W3C trace propagation)
```

A shared `spec/telemetry-api.yaml` defines the required API surface. CI validates that both Python and TypeScript exports conform to it. Cross-language distributed tracing is tested end-to-end via W3C `traceparent` propagation.

## Quality

- 100% branch coverage (Python + TypeScript)
- 100% mutation kill score (mutmut + Stryker)
- Strict type checking (mypy + ty + tsc)
- CodeQL SAST scanning
- SHA-pinned GitHub Actions
- Sigstore artifact signing
- CycloneDX SBOM on releases

## Documentation

- [Configuration Reference](docs/CONFIGURATION.md) — all environment variables
- [API Reference](docs/API.md) — Python function signatures and examples
- [Architecture](docs/ARCHITECTURE.md) — component design and data flow
- [Internals](docs/INTERNALS.md) — implementation details
- [Conventions](docs/CONVENTIONS.md) — event naming and schema rules
- [Operations Runbook](docs/OPERATIONS.md) — troubleshooting and CQ matrix
- [Production Profiles](docs/PRODUCTION_PROFILES.md) — recommended configs
- [Release Runbook](docs/RELEASE.md) — versioning and publishing
- [TypeScript README](typescript/README.md) — TypeScript-specific docs
- [Examples](examples/README.md) — Python and TypeScript examples

## License

Apache-2.0. See [LICENSES/](LICENSES/).
