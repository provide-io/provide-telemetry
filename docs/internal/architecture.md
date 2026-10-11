# Architecture

## Goals

- Unified telemetry facade across the repo's Python, TypeScript, Go, Rust, and
  C# implementations.
- Safe defaults with optional OpenTelemetry runtime integration.
- Strict event naming and schema validation for consistent analytics.
- Predictable behavior under async workloads.

## High-Level Layers

1. Public facade (`provide.telemetry`): stable imports and setup lifecycle.
2. Configuration (`TelemetryConfig`): env-driven, strongly typed runtime config.
3. Logging: structlog processors with contextvars-backed request/session
   propagation and optional OTLP log export.
4. Tracing: OTel provider if available, no-op tracer fallback otherwise.
5. Metrics: OTel meter provider if available, in-process fallback wrappers
   otherwise. The provider carries an OTLP push reader, a Prometheus pull
   reader, or both side by side; the pull reader is served by an ASGI handler
   (`metrics_handler()`) and/or a standalone listener.
6. ASGI/WebSocket adapters: request context extraction and propagation.
7. Rust crate (`rust/`): guard-based context API, fallback facades, and optional
   `otel` feature wiring.

## High-Level Component Flow

```mermaid
flowchart TD
  A["Client Code"] --> B["provide.telemetry facade"]
  B --> C["setup/runtime config"]
  B --> D["logger pipeline"]
  B --> E["tracing provider"]
  B --> F["metrics API"]
  D --> G["OTel log exporter (optional)"]
  D --> H["structlog local rendering"]
  E --> I["OTel tracer (if extras installed)"]
  E --> J["no-op tracer fallback"]
  F --> K["OTel meter instruments (if extras installed)"]
  F --> L["in-process fallback instruments"]
  K --> K1["OTLP periodic reader (push)"]
  K --> K2["Prometheus pull reader"]
  K2 --> K3["metrics_handler() / standalone listener"]
  M --> K3
  D --> M["health counters/self-observability"]
  E --> M
  F --> M
```

## Runtime Model

- One telemetry setup per process (`setup_telemetry`) guarded by a lock.
- Provider initialization is idempotent and lock-protected.
- `shutdown_telemetry` is serialized with `setup_telemetry` under the same lock
  to prevent setup/shutdown races.
- `shutdown_telemetry` marks setup state as not-ready before provider teardown.
- Runtime policy changes (`sampling`, `backpressure`, `exporter`) are
  hot-reloadable in-process.
- Provider-changing reconfiguration is constrained by OpenTelemetry's
  process-global providers; after real OTel providers are installed, those
  changes require process restart rather than in-process replacement.
- Runtime policy updates snapshot runtime state before storing/applying it.
- Active runtime state is read back via `get_runtime_config()` /
  `GetRuntimeConfig()` / `getRuntimeConfig()` rather than by mutating a
  caller-owned config object.
- Python uses `contextvars` for async task safety; Rust preserves the same
  behavior with scoped guards over task-local/thread-local snapshots.

## Async Safety

### Guaranteed

- Request context fields are isolated per task via `contextvars`.
- Trace context remains stable across await boundaries inside traced async
  callables.
- Setup and shutdown routines are race-safe for concurrent callers in the same
  process.
- Rust guard-based context bindings restore prior request/session/trace state on
  `Drop`.

### Scope Limits

- State is process-local (multi-process workers each initialize their own
  providers).
- Export delivery guarantees depend on OTel exporters and backend availability.

## Failure and Fallback Strategy

- Missing OTel dependencies: tracing falls back to no-op tracer objects and
  metrics fall back to in-process wrappers.
- Invalid event names/required keys: deterministic schema errors.
- Export endpoint absent: tracing/metrics providers still initialize safely.

## Request Lifecycle Sequence

```mermaid
sequenceDiagram
  participant C as Client
  participant M as TelemetryMiddleware
  participant P as Propagation/Context
  participant L as Logger/Tracer/Meter
  participant X as Exporter/Fallback

  C->>M: HTTP/WS request (headers)
  M->>P: extract x-request-id/x-session-id + W3C headers
  P-->>M: bind contextvars
  M->>L: app emits logs/spans/metrics
  L->>X: sampled + guarded signal dispatch
  alt OTel configured and healthy
    X-->>L: export succeeds
  else exporter unavailable/timeout/unsupported
    X-->>L: fallback path + health/drop accounting
  end
  M->>P: clear propagation and request context
  M-->>C: response
```

## Processor Pipeline

```mermaid
flowchart LR
    A["merge_contextvars"] --> A2["merge_runtime_context"]
    A2 --> B["inject_logger_name"]
    B --> B2["inject_das_fields"]
    B2 --> C["add_log_level + canonicalize_level"]
    C --> D{"include_timestamp?"}
    D -->|yes| E["TimeStamper"]
    D -->|no| H2{"module_levels?"}
    E --> H2
    H2 -->|yes| H3["make_level_filter"]
    H2 -->|no| I["apply_sampling (consent, sampling, backpressure)"]
    H3 -->|DropEvent| X["discarded"]
    H3 --> I
    I -->|DropEvent| X
    I --> F["harden_input"]
    F --> G["add_standard_fields"]
    G --> G2["add_error_fingerprint"]
    G2 --> H["enforce_event_schema"]
    H --> J["sanitize_sensitive_fields (PII + receipts)"]
    J --> K{"include_caller?"}
    K -->|yes| L["CallsiteParameterAdder"]
    K -->|no| M{"fmt == json?"}
    L --> M
    M -->|yes| M2["rename_event_to_message"]
    M -->|no| N["render_with_backpressure_extra"]
    M2 --> N
    N --> O["console / json / pretty"]
```

Admission (`apply_sampling`) runs before any payload work, in the canonical
stage order of `spec/pipeline_fixtures.yaml` (consent → sampling →
backpressure → hardening → pii → receipt → local → backend → health →
release). A refused record is counted as `dropped` (`apply_sampling` counts
a consent refusal; the sampler and `try_acquire` count their own) and releases
a `None` ticket. An admitted record carries its ticket to the stdlib handler boundary,
which counts it `emitted` after the local and backend handlers return and then
releases the ticket. A level-filtered record is not a drop.
The reserved root fields (`reserved_root_fields` in `spec/telemetry-api.yaml`)
are stamped by the SDK, replacing any caller-supplied value of the same name:
`merge_runtime_context` stamps `trace_id`/`span_id` from a live span, and
`add_standard_fields` stamps `service`/`env`/`version` from non-empty config
values (JSON output only; the human renderers omit identity). Records that reach the handlers without passing this chain (stdlib
`logging` calls) are hardened and sanitized by `logger/_foreign_records.py`;
`_record_marker.py` marks records the chain already processed.

## Setup and Shutdown State Machine

```mermaid
stateDiagram-v2
    [*] --> Uninitialized
    Uninitialized --> Ready: setup_telemetry() [lifecycle coordinator]
    Ready --> Ready: setup_telemetry() [idempotent, no-op]
    Ready --> Ready: update_runtime_config() [hot reload, live config required]
    Ready --> Stopped: shutdown_telemetry() [bounded drain, resets always run]
    Stopped --> Ready: setup_telemetry() [re-setup]
```

The `RuntimeState` enum carries the seven-state vocabulary shared with Go, Rust,
TypeScript and C# (`local` / `starting` / `ready` / `degraded` / `reconfiguring`
/ `stopping` / `stopped`); Python's runtime reports `ready` and `stopped` and
reserves the rest for parity with runtimes that surface intermediate states.

## Resilience Flow

```mermaid
flowchart TD
    A["Export attempt"] --> B{"Circuit breaker open?"}
    B -->|open, within cooldown| C{"fail_open?"}
    B -->|closed or half-open| D["Submit to ThreadPoolExecutor"]
    D --> E{"Completed within timeout?"}
    E -->|yes| F["record_export_success, reset timeouts"]
    E -->|timeout| G["Increment consecutive timeouts"]
    G --> H{"Threshold reached (3)?"}
    H -->|yes| I["Trip circuit breaker, record timestamp"]
    H -->|no| J{"Retries remaining?"}
    I --> J
    J -->|yes| K["Backoff sleep, then retry"] --> D
    J -->|no| C
    D -->|other error| L["record_export_failure, reset timeouts"]
    L --> J
    C -->|true| M["Return None"]
    C -->|false| N["Raise exception"]
```

## Subsystem Inventory

| Module | Responsibility |
|--------|---------------|
| `__init__.py` | Public API facade, 122 exports (declarations only) |
| `_lazy.py` | PEP 562 symbol registry the facade resolves through |
| `setup.py` | Lock-protected init/shutdown coordinator with rollback |
| `config.py` | Pydantic-free dataclass config, env var parsing |
| `_config_validation.py` | Env-parsing validation helpers for `config.py` |
| `_config_prometheus.py` | Parsing and validation of the Prometheus metrics settings |
| `runtime.py` | Hot-reload API, provider-change detection, `TelemetryRuntime` |
| `_lifecycle.py` | Lifecycle coordinator publishing immutable runtime generations |
| `_runtime_types.py` | `RuntimeState` / `FlushResult` / `ReconfigureResult` shared shapes |
| `_runtime_policies.py` | Applies sampling/backpressure/exporter policy blocks |
| `_provider_drain.py` | Per-signal provider drain with honest per-signal outcomes |
| `_endpoint.py` | OTLP endpoint validation |
| `_otlp_tls.py` | Per-signal OTLP TLS file checks; an unreadable file leaves only that signal's exporter unbuilt |
| `_masking.py` | Masks OTLP credentials in config representations |
| `_resource.py` | OTel resource precedence ladder (default < `OTEL_*` env < config) |
| `_otel.py` | Lazy OTel import helpers, W3C context attach/inject |
| `logger/core.py` | Structlog pipeline, handler construction |
| `logger/handlers.py` | Stdlib logging handlers used by the structlog pipeline |
| `logger/_foreign_records.py` | Hardening and PII for stdlib records that bypassed the structlog chain |
| `logger/sink.py` / `logger/console.py` / `logger/_windows_console.py` | Log destination, and what that stream can render |
| `logger/_otel_logs.py` | Stateless OTel log-provider wiring |
| `logger/context.py` | Contextvars for request/session context |
| `logger/processors.py` | Processor chain: admission, hardening, standard fields, schema, PII |
| `_record_marker.py` | Marker on a LogRecord this SDK already hardened and sanitized |
| `logger/pretty.py` | Pretty renderer with configurable colors |
| `tracing/provider.py` | OTel TracerProvider or no-op fallback |
| `tracing/context.py` | Contextvars for trace_id/span_id |
| `tracing/context_runtime.py` | Cross-context-safe OTel attach/detach (avoids `Token.reset()` raising across contexts) |
| `tracing/decorators.py` | `@trace` decorator (sync and async) |
| `tracing/span.py` | Sync block-level `span()` context manager and span attribute helpers |
| `metrics/provider.py` | OTel MeterProvider (OTLP reader and/or Prometheus pull reader) or fallback |
| `metrics/observable.py` | Observable (callback-reported) instruments |
| `metrics/prometheus.py` | Prometheus pull reader, endpoint status, Tier 2 ASGI `metrics_handler()`, health series |
| `metrics/_prom_listener.py` | Tier 3 standalone listener with exporter-toolkit web config (TLS, basic auth) |
| `metrics/_prom_render.py` / `metrics/_prom_names.py` | Text exposition rendering, metric/label name translation |
| `metrics/_health_otlp.py` | `PROVIDE_METRICS_HEALTH_OTLP`: health series as observable instruments on the SDK's own provider |
| `metrics/api.py` | `counter()`, `gauge()`, `histogram()` constructors |
| `metrics/instruments.py` | Re-export shim for Counter/Gauge/Histogram (delegates to `fallback.py`) |
| `metrics/fallback.py` | In-process fallback Counter/Gauge/Histogram with sampling, backpressure, exemplar, and cardinality guard |
| `classification.py` | Data classification engine with per-field sensitivity rules |
| `consent.py` | Consent-aware telemetry collection gate |
| `receipts.py` | Cryptographic redaction receipts for audit trails |
| `schema/events.py` | Event name validation, required-key enforcement |
| `sampling.py` | Per-signal probabilistic sampling with overrides |
| `backpressure.py` | Bounded queue ticket system |
| `resilience.py` | Retry, timeout, circuit breaker, ThreadPoolExecutor |
| `resilient_exporter.py` | Per-export resilience wrappers so every `export()` runs under the policy, not just exporter construction |
| `pii.py` | PII rule engine with span-scoped secret detection (built-in + custom patterns) and nested traversal |
| `_secret_patterns_generated.py` | Built-in secret patterns, generated from `spec/secret_patterns.yaml` — do not edit |
| `headers.py` | Shared, safe header extraction (`get_header`) |
| `cardinality.py` | TTL-based attribute cardinality guards |
| `health.py` | Self-observability counters and snapshot |
| `propagation.py` | W3C traceparent/tracestate/baggage extraction |
| `slo.py` | RED/USE metric helpers |
| `exceptions.py` | TelemetryError, ConfigurationError, ProviderImmutableError |
| `levels.py` | Canonical severity ladder and string-to-level converter |
| `asgi/middleware.py` | ASGI middleware for request context |
| `asgi/websocket.py` | WebSocket context helpers |
| `testing.py` | Opt-in pytest plugin for per-test telemetry isolation |

## Governance Modules

Governance is part of the mandatory API surface in all five languages:
`classification`, `consent`, and `receipts` are always linked and loaded by
default. `spec/validate_conformance.py` enforces this through
`_GOVERNANCE_LANGUAGES`, which lists Python, TypeScript, Go, Rust, and C#. Core
signal paths (logging, tracing, metrics, schema handling, health, resilience)
still execute when governance policies are permissive.

Governance symbols are marked `required: true` in `spec/telemetry-api.yaml`.

## Testing Strategy

- Unit tests with branch coverage for all local logic and fallback paths.
- Optional-extras tests to validate real OTel imports.
- Integration smoke test with local OTLP collector (manual/nightly CI).
- Python, TypeScript, Go, Rust, and C# each validate against the shared API
  spec; Rust additionally runs `cargo fmt`, `cargo clippy`, `cargo test`, and
  `cargo test --features otel`, and C# builds its solution with `-warnaserror`.
- Strip-governance verification artifacts were removed; this parity slice now
  validates governance always-on behavior.
