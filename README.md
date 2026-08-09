# Provide Telemetry

Unified telemetry library for structured logging, distributed tracing, and metrics across Python, TypeScript, Go, Rust, and C#. Graceful OTel degradation — works without OpenTelemetry installed, activates full OTLP export (traces, metrics, logs) when the OTel SDK is present. Rust requires the `otel` cargo feature (`cargo build --features otel`); C# requires the separate `Provide.Telemetry.OpenTelemetry` package plus a one-time `OpenTelemetryBackendRegistration.Register()` call.

[![🐍 CI — Python](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-python.yml/badge.svg)](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-python.yml)
[![🟦 CI — TypeScript](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-typescript.yml/badge.svg)](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-typescript.yml)
[![🐹 CI — Go](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-go.yml/badge.svg)](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-go.yml)
[![🟣 CI — C#](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-csharp.yml/badge.svg)](https://github.com/provide-io/provide-telemetry/actions/workflows/ci-csharp.yml)
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

**C#:**

```bash
dotnet add package Provide.Telemetry                  # core, BCL-only — no OpenTelemetry dependency
dotnet add package Provide.Telemetry.OpenTelemetry    # + OTLP delivery for all three signals
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
import {
  setupTelemetry,
  getConfig,
  getLogger,
  registerOtelProviders,
  shutdownTelemetry,
} from '@provide-io/telemetry';

setupTelemetry({ serviceName: 'my-app' });
// Required to actually export to an OTLP collector — setupTelemetry alone
// configures policies but does not register SDK providers.
await registerOtelProviders(getConfig());

const log = getLogger('api');
log.info({ event: 'app.start.ok', requestId: 'req-1' });
await shutdownTelemetry();
```

All implementations share the same API surface, event naming conventions, and configuration environment variables. The Rust crate lives in `rust/` and uses guard-based context binding for task-safe restoration; the C# packages live in `csharp/` and offer the same scoped restoration through `IDisposable` context scopes over `AsyncLocal<T>`. See the [Capability Matrix](https://github.com/provide-io/provide-telemetry/blob/main/docs/CAPABILITY_MATRIX.md) for the differences that are real — notably that C# ships no ANSI pretty renderer and no HTTP request-lifecycle middleware.

**On wire-format parity**: local JSON logs use a canonical snake_case envelope across implementations (`timestamp`, `level`, `message`, `logger_name`, `service`, `env`, `version`, `trace_id`, `span_id`, plus event fields). The parity harness in `spec/` also normalizes legacy OTel keys (`service.name`, `service.env`, `service.version`, `trace.id`, `span.id`) when present to keep comparisons stable for older emit paths.

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

All implementations export equivalent APIs (signatures vary per language idiom):

| Category | Functions |
|----------|-----------|
| Lifecycle | `setup_telemetry()`, `flush_telemetry()`, `shutdown_telemetry()` |
| Logging | `get_logger()`, `bind_context()`, `clear_context()` |
| Tracing | `get_tracer()`, `trace` (decorator/wrapper), `extract_w3c_context()` |
| Metrics | `counter()`, `gauge()`, `histogram()` |
| Policies | `set_sampling_policy()`, `set_queue_policy()`, `set_exporter_policy()` |
| Safety | `register_cardinality_limit()`, `register_pii_rule()`, `replace_pii_rules()`, `get_pii_rules()` |
| Health | `get_health_snapshot()` |
| Runtime | `get_runtime_config()`, `get_runtime_status()`, `update_runtime_config()`, `reconfigure_telemetry()`, `reload_runtime_from_env()` |

Full reference: [Python API](https://github.com/provide-io/provide-telemetry/blob/main/docs/API.md) | [TypeScript API](https://github.com/provide-io/provide-telemetry/blob/main/typescript/README.md) | [Go API](https://github.com/provide-io/provide-telemetry/blob/main/go/README.md) | [Rust crate](https://github.com/provide-io/provide-telemetry/tree/main/rust) | [C# packages](https://github.com/provide-io/provide-telemetry/blob/main/csharp/README.md)

## Polyglot Architecture

```
provide-telemetry/
  src/provide/telemetry/    # Python package
  typescript/             # TypeScript package (@provide-io/telemetry)
  go/                     # Go module (github.com/provide-io/provide-telemetry/go)
  rust/                   # Rust crate (provide-telemetry)
  csharp/                 # .NET packages (Provide.Telemetry, Provide.Telemetry.OpenTelemetry)
  spec/                   # Canonical API spec — all languages validate against it
  e2e/                    # Cross-language E2E tests (W3C trace propagation)
```

A shared `spec/telemetry-api.yaml` defines the required API surface. CI validates that Python, TypeScript, Go, Rust, and C# exports conform to it, and all five run the shared behavioral, contract, config, and runtime probes in `spec/`. The `e2e/` distributed-tracing suite, which propagates a real W3C `traceparent` between two live services, currently covers Python, TypeScript, Go, and Rust — C# is not yet wired into it.

## Quality

- Coverage gates: full 100% gates for Python, TypeScript, Go, and Rust, with language-appropriate threshold interpretation. C# is the one exception, and a recorded one: `ci-csharp.yml` merges every Cobertura report the run emits and enforces floors of 99% line / 97% branch (measured 99.60% / 97.94% across 685 tests), ratcheted up and never down.
- Python runs mutmut and fails on any survivor, timeout, suspicious, or no-tests result — the 95% score floor is an extra guard, not the bar; Go requires both 100% gremlins efficacy and 100% mutant coverage; TypeScript uses Stryker with a 95% core break threshold plus an 80% OTLP transport ratchet; Rust requires a 100% cargo-mutants kill rate across eight blocking shards whenever Rust implementation or test code changes. C# runs Stryker.NET 4.16 over both packages with a break threshold of 79, against a measured 80.10% (1337 killed of 1678 scored, 2026-08-09) — the honest baseline for a gate that is one release old, not a target. Its surviving mutants are enumerated in `csharp/stryker-config.json`.
- Strict type checking (mypy + ty + tsc)
- CodeQL SAST scanning
- SHA-pinned third-party GitHub Actions
- Sigstore artifact signing
- CycloneDX SBOM on releases

## Documentation

- [Configuration Reference](https://github.com/provide-io/provide-telemetry/blob/main/docs/CONFIGURATION.md) — all environment variables
- [API Reference](https://github.com/provide-io/provide-telemetry/blob/main/docs/API.md) — shared semantic contract and Python-centered examples
- [Capability Matrix](https://github.com/provide-io/provide-telemetry/blob/main/docs/CAPABILITY_MATRIX.md) — core guarantees vs feature-gated or idiomatic differences
- [Architecture](https://github.com/provide-io/provide-telemetry/blob/main/docs/ARCHITECTURE.md) — component design and data flow
- [Developer Experience Rubric](https://github.com/provide-io/provide-telemetry/blob/main/docs/DX_RUBRIC.md) — criteria for cross-language consistency and usability
- [Internals](https://github.com/provide-io/provide-telemetry/blob/main/docs/INTERNALS.md) — implementation details
- [Conventions](https://github.com/provide-io/provide-telemetry/blob/main/docs/CONVENTIONS.md) — event naming and schema rules
- [Operations Runbook](https://github.com/provide-io/provide-telemetry/blob/main/docs/OPERATIONS.md) — troubleshooting and CQ matrix
- [Quality Gap-to-Closure Checklist](https://github.com/provide-io/provide-telemetry/blob/main/docs/QUALITY_GAP_CLOSURE.md) — auditable coverage, fixture, and mutation gates
- [Polyglot Parity Roadmap](https://github.com/provide-io/provide-telemetry/blob/main/docs/PARITY_ROADMAP.md) — prioritized work to reach true behavioral parity
- [Production Profiles](https://github.com/provide-io/provide-telemetry/blob/main/docs/PRODUCTION_PROFILES.md) — recommended configs
- [Release Runbook](https://github.com/provide-io/provide-telemetry/blob/main/docs/RELEASE.md) — versioning and publishing
- [TypeScript README](https://github.com/provide-io/provide-telemetry/blob/main/typescript/README.md) — TypeScript-specific docs
- [Go README](https://github.com/provide-io/provide-telemetry/blob/main/go/README.md) — Go-specific docs
- [Rust crate](https://github.com/provide-io/provide-telemetry/tree/main/rust) — Rust-specific source and examples
- [C# README](https://github.com/provide-io/provide-telemetry/blob/main/csharp/README.md) — the two-package split and C#-specific usage
- [Examples](https://github.com/provide-io/provide-telemetry/blob/main/examples/README.md) — runnable examples for the polyglot repo

## License

Apache-2.0. See [LICENSES/](https://github.com/provide-io/provide-telemetry/tree/main/LICENSES).
