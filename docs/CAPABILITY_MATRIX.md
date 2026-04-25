# Capability Matrix

This matrix separates core guaranteed behavior from idiomatic differences and
feature-gated OTLP paths.

Legend:

- `core` — guaranteed by the shared semantic contract and parity suite
- `idiomatic` — intentionally language-specific surface difference
- `feature-gated` — supported, but only when the language-specific OTLP feature
  path is enabled

| Capability | Python | TypeScript | Go | Rust | Contract |
| --- | --- | --- | --- | --- | --- |
| Canonical JSON log envelope (`service`, `env`, `version`, `logger_name`, trace/span IDs, timestamp policy) | core | core | core | core | core guaranteed |
| Lazy logger init uses effective env config | core | core | core | core | core guaranteed |
| Strict-schema rejection emits `_schema_error` instead of dropping the record | core | core | core | core | core guaranteed |
| Required-key rejection emits `_schema_error` instead of dropping the record | core | core | core | core | core guaranteed |
| Invalid config fails fast at setup | core | core | core | core | core guaranteed |
| Fail-open exporter initialization degrades to fallback without marking providers installed | core | core | core | feature-gated | core guaranteed when OTLP path is enabled |
| Shutdown followed by setup restores the same runtime-status shape | core | core | core | core | core guaranteed |
| `get_runtime_config()` returns effective config after setup (Python/TS also return env fallback before setup; Go/Rust return nil/None) | core | core | core | core | core guaranteed after setup; pre-setup behavior varies |
| `get_runtime_status()` exposes `setup_done`, `signals`, `providers`, `fallback`, and `setup_error` | core | core | core | core | core guaranteed |
| Real OTLP traces export | core | core | core | feature-gated | feature/dependency gated |
| Real OTLP metrics export | core | core | core | feature-gated | feature/dependency gated |
| Real OTLP logs export | core | core | core | feature-gated | feature/dependency gated |
| Guard-based context restoration | idiomatic | no | no | idiomatic | idiomatic language difference |
| Browser log capture / React helpers | no | idiomatic | no | no | idiomatic language difference |
| `Gauge.value` returns aggregate across all attribute sets | aggregate | last-reading | last-reading | last-reading | capability difference — see notes |
| ASGI/HTTP request-lifecycle middleware (binds request/session context, extracts W3C baggage) | core | core | core | missing | known gap |
| `PROVIDE_LOG_FORMAT=pretty` renderer | core | core | core | missing | Rust gap only |
| Metrics fallback export on shutdown when OTel is unavailable | stderr JSON | no | no | no | capability difference — see notes |

Notes:

- Rust OTLP export requires the `otel` cargo feature.
- TypeScript OTLP export requires the optional OpenTelemetry peer dependencies.
- Python OTLP export requires the `otel` extras.
- Go OTLP export is built into the module, but still follows fail-open setup and
  runtime fallback semantics when provider construction fails.
- Gauge semantics: Python tracks per-attribute-set values and exposes the
  aggregate in-process `value` as the sum across all attribute sets
  (`src/provide/telemetry/metrics/fallback.py`). TypeScript, Go, and Rust
  follow the OTel-native last-reading model — `value` returns the most recent
  value written, regardless of attribute set. The OTel-exported metric stream
  is consistent across all four languages (per-series last reading); only the
  in-process `.value()` accessor differs. Cross-language comparisons of the
  aggregate accessor are not supported.
- ASGI/HTTP middleware: Python ships `provide.telemetry.asgi.TelemetryMiddleware`
  (`src/provide/telemetry/asgi/middleware.py`) and TypeScript and Go ship
  equivalent request-lifecycle middleware. Rust does not provide a pre-built
  axum/hyper middleware; users must call `bind_context()` / `clear_context()`
  manually inside handlers and extract W3C traceparent/tracestate via
  `extract_w3c_context()`.
- Pretty log rendering: Python, TypeScript, and Go all honour
  `PROVIDE_LOG_FORMAT=pretty` with an ANSI renderer. Go's implementation
  lives in `go/logger_pretty.go` and uses stdlib-only ANSI escapes with
  TTY-gated color. Rust's logger emitter (`rust/src/logger/emit.rs`)
  only implements `console` and `json`; setting `pretty` on Rust falls
  back to the console formatter.
- Metrics fallback export: without the `otel` feature, Rust's metrics
  accumulate in-process (`rust/src/metrics.rs`) but are never exported.
  Python's fallback (`src/provide/telemetry/metrics/fallback.py`) flushes a
  JSON snapshot to stderr on shutdown. TypeScript and Go behave like Rust in
  this regard.
