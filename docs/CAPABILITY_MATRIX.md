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
| `flush_telemetry()` drains installed providers without tearing them down, and reports a drain it could not complete | core | core | core | core | core guaranteed |
| A tracer/meter provider a *host application* installed on the OTel globals is emitted through and reported as installed | auto-detected | auto-detected | auto-detected | host-asserted | core guaranteed; detection mechanism is idiomatic |
| Real OTLP traces export | core | core | core | feature-gated | feature/dependency gated |
| Real OTLP metrics export | core | core | core | feature-gated | feature/dependency gated |
| Real OTLP logs export | core | core | core | feature-gated | feature/dependency gated |
| Guard-based context restoration | idiomatic | no | no | idiomatic | idiomatic language difference |
| Browser log capture / React helpers | no | idiomatic | no | no | idiomatic language difference |
| `Gauge.value` returns aggregate across all attribute sets | aggregate | last-reading | last-reading | last-reading | capability difference — see notes |
| Counter / gauge / histogram values readable from the instrument | core | core | concrete type only | core | core guaranteed; Go's exported `Histogram` interface declares only `Record` |
| ASGI/HTTP request-lifecycle middleware (binds request/session context, extracts W3C baggage) | core | core | core | missing | known gap |
| `PROVIDE_LOG_FORMAT=pretty` renderer | core | core | core | core | core guaranteed across all four languages |
| Metrics fallback export on shutdown when OTel is unavailable | stderr JSON | no | no | no | capability difference — see notes |

Notes:

- Instrument value readback is pinned cross-language by the
  `metric_instrument_values` runtime-probe case, which compares counter, gauge
  and histogram output across all four. Go is the outlier: its exported
  `Counter`/`Gauge`/`Histogram` interfaces declare only the write method, so a
  consumer holding the interface cannot read a value back — the concrete
  fallback types have `Value()`, `Count()` and `Sum()`, and the probe reaches
  them by type assertion. Note also that Go names the histogram sum `Sum` where
  the other three say `total`. Neither is fixed here; changing an exported
  interface is a separate decision.
- The `Real OTLP * export` rows are only as good as what verifies them. Each
  language has a collector-backed integration job that asserts the named signal
  reaches a real OTel collector; the cross-language parity harness does not
  cover them, because its contract probes carry no SDK dependency by design and
  so verify facade behaviour rather than bytes on the wire. TypeScript's logs
  row was wrong for a period — the row said `core` while the log processor had
  no exporter and dropped every record — and the integration test did not catch
  it because it asserted only `providers.traces`. If you add a signal or a
  language, the collector job is the row's evidence: make it assert every signal
  it claims.
- Rust cannot auto-detect a host-installed provider: `opentelemetry`'s
  `global::tracer_provider()` returns an opaque `GlobalTracerProvider` with no
  downcast and no `is_noop`. The host asserts it instead, via
  `adopt_global_providers(AdoptedProviders { traces, metrics })`. The observable
  contract is identical across all four and is pinned by the
  `host_provider_adoption` runtime-probe case.
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
- Pretty log rendering: all four languages honour
  `PROVIDE_LOG_FORMAT=pretty` with an ANSI renderer. Python's lives in
  `src/provide/telemetry/logger/pretty.py`, TypeScript's in
  `typescript/src/pretty.ts`, Go's in `go/logger_pretty.go`, and Rust's
  in `rust/src/logger/pretty.rs`. All four gate ANSI output on stderr
  being a TTY, honour `PROVIDE_LOG_PRETTY_KEY_COLOR` and
  `PROVIDE_LOG_PRETTY_VALUE_COLOR`, honour `PROVIDE_LOG_PRETTY_FIELDS`,
  and emit the same standard field set (timestamp, level, message, kv
  pairs). The Go row covers the root
  `github.com/provide-io/provide-telemetry/go` package; compatibility
  subpackages intentionally expose narrower surfaces.
- Metrics fallback export: without the `otel` feature, Rust's metrics
  accumulate in-process (`rust/src/metrics.rs`) but are never exported.
  Python's fallback (`src/provide/telemetry/metrics/fallback.py`) flushes a
  JSON snapshot to stderr on shutdown. TypeScript and Go behave like Rust in
  this regard.
