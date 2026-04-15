# Provide Telemetry

Unified telemetry library for structured logging, distributed tracing, and metrics across Python, TypeScript, Go, and Rust. Graceful OTel degradation — works without OpenTelemetry installed; Python, TypeScript, and Go activate full OTLP export when the OTel SDK is present. Rust provides API-shape parity with in-process fallback instrumentation; full OTel export is not yet implemented.

[![🐍 CI — Python](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-python.yml/badge.svg)](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-python.yml)
[![🟦 CI — TypeScript](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-typescript.yml/badge.svg)](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-typescript.yml)
[![🐹 CI — Go](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-go.yml/badge.svg)](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-go.yml)
[![🔒 CodeQL](https://github.com/provide-io/provide-telemetry/actions/workflows/codeql.yml/badge.svg)](https://github.com/provide-io/provide-telemetry/actions/workflows/codeql.yml)

## Install

**Python:**

```bash
pip install provide-telemetry              # core (structlog)
pip install "provide-telemetry[otel]"      # + OpenTelemetry export
```

**TypeScript:**

```bash
npm install @provide-io/telemetry             # core (pino + @opentelemetry/api)
```

**Rust:**

```bash
cargo add provide-telemetry
cargo add provide-telemetry --features otel
```

## Quick Start

**Python:**

```python
from provide.telemetry import setup_telemetry, shutdown_telemetry, get_logger, event

setup_telemetry()
log = get_logger(__name__)
log.info("app.start.ok", request_id="req-1")
shutdown_telemetry()
```

**TypeScript:**

```typescript
import { setupTelemetry, getLogger, shutdownTelemetry } from '@provide-io/telemetry';

setupTelemetry({ serviceName: 'my-app' });
const log = getLogger('api');
log.info({ event: 'app.start.ok', requestId: 'req-1' });
await shutdownTelemetry();
```

All implementations share the same API surface, event naming conventions, and configuration environment variables. The Rust crate lives in `rust/` and uses guard-based context binding for task-safe restoration.

## Configuration

All runtime config is via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PROVIDE_TELEMETRY_SERVICE_NAME` | `provide-service` | Service identity |
| `PROVIDE_LOG_LEVEL` | `INFO` | Log level |
| `PROVIDE_LOG_FORMAT` | `console` | Renderer: `console`, `json`, or `pretty` |
| `PROVIDE_TELEMETRY_ENV` | `dev` | Deployment environment |
| `PROVIDE_TELEMETRY_VERSION` | `0.0.0` | Service version |
| `PROVIDE_TRACE_ENABLED` | `true` | Enable OTel tracing |
| `PROVIDE_METRICS_ENABLED` | `true` | Enable OTel metrics |

See the [Configuration Reference](https://github.com/provide-io/provide-telemetry/blob/main/docs/CONFIGURATION.md) for all 60+ environment variables.

## Event Naming

Event names follow the DA(R)S pattern — Domain, Action, (Resource), Status — as 3 or 4 dot-separated lowercase segments. `event()` returns a structured `Event` (a `str` subclass with `.domain`, `.action`, `.resource`, and `.status` fields):

```python
# Python
log.info("auth.login.success", user_id="u-123")
log.info(event("auth", "login", "failed"), reason="bad_password")
```

```typescript
// TypeScript
log.info({ event: 'auth.login.success', userId: 'u-123' });
```

See [Conventions](https://github.com/provide-io/provide-telemetry/blob/main/docs/CONVENTIONS.md) for full naming rules.

## API Surface

All implementations export equivalent APIs:

| Category | Functions |
|----------|-----------|
| Lifecycle | `setup_telemetry()`, `shutdown_telemetry()` |
| Logging | `get_logger()`, `bind_context()`, `clear_context()` |
| Tracing | `get_tracer()`, `trace` (decorator/wrapper), `extract_w3c_context()` |
| Metrics | `counter()`, `gauge()`, `histogram()` |
| Policies | `set_sampling_policy()`, `set_queue_policy()`, `set_exporter_policy()` |
| Safety | `register_cardinality_limit()`, `register_pii_rule()`, `replace_pii_rules()`, `get_pii_rules()` |
| Health | `get_health_snapshot()` |
| Runtime | `update_runtime_config()`, `reconfigure_telemetry()`, `reload_runtime_from_env()` |

Full reference: [Python API](https://github.com/provide-io/provide-telemetry/blob/main/docs/API.md) | [TypeScript API](https://github.com/provide-io/provide-telemetry/blob/main/typescript/README.md) | [Go API](https://github.com/provide-io/provide-telemetry/blob/main/go/README.md) | [Rust crate](https://github.com/provide-io/provide-telemetry/tree/main/rust)

## Polyglot Architecture

```
provide-telemetry/
  src/provide/telemetry/    # Python package
  typescript/             # TypeScript package (@provide-io/telemetry)
  go/                     # Go module (github.com/provide-io/provide-telemetry/go)
  rust/                   # Rust crate (provide-telemetry)
  spec/                   # Canonical API spec — all languages validate against it
  e2e/                    # Cross-language E2E tests (W3C trace propagation)
```

A shared `spec/telemetry-api.yaml` defines the required API surface. CI validates that Python, TypeScript, Go, and Rust exports conform to it. Cross-language distributed tracing is tested end-to-end via W3C `traceparent` propagation.

## Quality

- 100% branch coverage (Python + TypeScript + Go; Rust crate verified with `cargo test`)
- 100% mutation kill score (mutmut + Stryker + gremlins)
- Strict type checking (mypy + ty + tsc)
- CodeQL SAST scanning
- SHA-pinned GitHub Actions
- Sigstore artifact signing
- CycloneDX SBOM on releases

## Documentation

- [Configuration Reference](https://github.com/provide-io/provide-telemetry/blob/main/docs/CONFIGURATION.md) — all environment variables
- [API Reference](https://github.com/provide-io/provide-telemetry/blob/main/docs/API.md) — Python function signatures and examples
- [Architecture](https://github.com/provide-io/provide-telemetry/blob/main/docs/ARCHITECTURE.md) — component design and data flow
- [Internals](https://github.com/provide-io/provide-telemetry/blob/main/docs/INTERNALS.md) — implementation details
- [Conventions](https://github.com/provide-io/provide-telemetry/blob/main/docs/CONVENTIONS.md) — event naming and schema rules
- [Operations Runbook](https://github.com/provide-io/provide-telemetry/blob/main/docs/OPERATIONS.md) — troubleshooting and CQ matrix
- [Production Profiles](https://github.com/provide-io/provide-telemetry/blob/main/docs/PRODUCTION_PROFILES.md) — recommended configs
- [Release Runbook](https://github.com/provide-io/provide-telemetry/blob/main/docs/RELEASE.md) — versioning and publishing
- [TypeScript README](https://github.com/provide-io/provide-telemetry/blob/main/typescript/README.md) — TypeScript-specific docs
- [Go README](https://github.com/provide-io/provide-telemetry/blob/main/go/README.md) — Go-specific docs
- [Rust crate](https://github.com/provide-io/provide-telemetry/tree/main/rust) — Rust-specific source and examples
- [Examples](https://github.com/provide-io/provide-telemetry/blob/main/examples/README.md) — runnable examples for the polyglot repo

## License

Apache-2.0. See [LICENSES/](https://github.com/provide-io/provide-telemetry/tree/main/LICENSES).
