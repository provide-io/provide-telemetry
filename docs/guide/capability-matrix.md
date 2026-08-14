# Capability Matrix

This matrix separates core guaranteed behavior from idiomatic differences and
feature-gated OTLP paths.

Legend:

- `core` — guaranteed by the shared semantic contract and parity suite
- `idiomatic` — intentionally language-specific surface difference
- `feature-gated` — supported, but only when the language-specific OTLP feature
  path is enabled

| Capability | Python | TypeScript | Go | Rust | C# | Contract |
| --- | --- | --- | --- | --- | --- | --- |
| Canonical JSON log envelope (`service`, `env`, `version`, `logger_name`, trace/span IDs, timestamp policy) | core | core | core | core | core | core guaranteed |
| Lazy logger init uses effective env config | core | core | core | core | core | core guaranteed |
| Strict-schema rejection emits `_schema_error` instead of dropping the record | core | core | core | core | core | core guaranteed |
| Required-key rejection emits `_schema_error` instead of dropping the record | core | core | core | core | core | core guaranteed |
| Invalid config fails fast at setup | core | core | core | core | core | core guaranteed |
| Fail-open exporter initialization degrades to fallback without marking providers installed | core | core | core | feature-gated | feature-gated | core guaranteed when OTLP path is enabled |
| Shutdown followed by setup restores the same runtime-status shape | core | core | core | core | core | core guaranteed |
| `get_runtime_config()` returns effective config after setup (Python/TS also return env fallback before setup; Go/Rust/C# return nil/None/null) | core | core | core | core | core | core guaranteed after setup; pre-setup behavior varies |
| `get_runtime_status()` exposes `setup_done`, `signals`, `providers`, `fallback`, and `setup_error` | core | core | core | core | core | core guaranteed |
| `flush_telemetry()` drains installed providers without tearing them down, and reports a drain it could not complete | core | core | core | core | core | core guaranteed |
| A tracer/meter provider a *host application* installed on the OTel globals is emitted through and reported as installed | auto-detected | auto-detected | auto-detected | host-asserted | host-asserted | core guaranteed; detection mechanism is idiomatic |
| Real OTLP traces export | core | core | core | feature-gated | feature-gated | feature/dependency gated |
| Real OTLP metrics export | core | core | core | feature-gated | feature-gated | feature/dependency gated |
| Real OTLP logs export | core | core | core | feature-gated | feature-gated | feature/dependency gated |
| Guard-based context restoration | idiomatic | no | no | idiomatic | idiomatic | idiomatic language difference |
| Browser log capture / React helpers | no | idiomatic | no | no | no | idiomatic language difference |
| `Gauge.value` returns aggregate across all attribute sets | aggregate | last-reading | last-reading | last-reading | last-reading | capability difference — see notes |
| Counter / gauge / histogram values readable from the instrument | core | core | concrete type only | core | core | core guaranteed; Go's exported `Histogram` interface declares only `Record` |
| ASGI/HTTP request-lifecycle middleware (binds request/session context, extracts W3C baggage) | core | missing | missing | missing | missing | known gap — Python only |
| `PROVIDE_LOG_FORMAT=pretty` renderer | core | core | core | core | no ANSI | core guaranteed in four languages — see notes |
| Metrics fallback export on shutdown when OTel is unavailable | no | no | no | no | no | uniform — fallback state drops on shutdown in every language; see notes |

Notes:

- Instrument value readback is pinned cross-language by the
  `metric_instrument_values` runtime-probe case, which compares counter, gauge
  and histogram output across all five. Go is the outlier: its exported
  `Counter`/`Gauge`/`Histogram` interfaces declare only the write method, so a
  consumer holding the interface cannot read a value back — the concrete
  fallback types have `Value()`, `Count()` and `Sum()`, and the probe reaches
  them by type assertion. C#'s `ICounter`/`IGauge`/`IHistogram` do declare the
  readers (`Value`, `Count`, `Sum`), so the interface is enough. Note that Go
  and C# both name the histogram sum `Sum` where the other three say `total`;
  the C# probe renames it at the boundary. Neither is fixed here; changing an
  exported interface is a separate decision.
- The `Real OTLP * export` rows are only as good as what verifies them.
  Python, TypeScript, Go and Rust each have a collector-backed integration job
  that asserts the named signal reaches a real OTel collector; the
  cross-language parity harness does not cover them, because its contract
  probes carry no SDK dependency by design and so verify facade behaviour
  rather than bytes on the wire. TypeScript's logs row was wrong for a period
  — the row said `core` while the log processor had no exporter and dropped
  every record — and the integration test did not catch it because it asserted
  only `providers.traces`. **C# is the one language whose OTLP rows have no
  blocking CI evidence**: its collector assertion lives in
  `csharp/tests/Provide.Telemetry.Tests/OpenObserveIntegrationTests.cs`, which
  asserts all three signals but is a `SkippableFact` that self-skips when
  `OPENOBSERVE_*` is unset, and `ci-csharp.yml` supplies no such credentials.
  The rows record what the integration package implements
  (`OpenTelemetryBackend.InstallTraces` / `InstallMetrics` / `InstallLogs`), not
  what CI proves. If you add a signal or a language, the collector job is the
  row's evidence: make it assert every signal it claims.
- Rust and C# cannot auto-detect a host-installed provider. In Rust,
  `opentelemetry`'s `global::tracer_provider()` returns an opaque
  `GlobalTracerProvider` with no downcast and no `is_noop`; the host asserts it
  instead, via `adopt_global_providers(AdoptedProviders { traces, metrics })`.
  C#'s core package names no OpenTelemetry type at all, so it has nothing to
  inspect; the host asserts adoption via
  `TelemetryBackendRegistry.MarkHostProviders(traces:, metrics:, logs:)`. The
  observable contract is identical across all five and is pinned by the
  `host_provider_adoption` runtime-probe case.
- Rust OTLP export requires the `otel` cargo feature.
- TypeScript OTLP export requires the optional OpenTelemetry peer dependencies.
- Python OTLP export requires the `otel` extras.
- Go OTLP export is built into the module, but still follows fail-open setup and
  runtime fallback semantics when provider construction fails.
- C# OTLP export requires the separate `Provide.Telemetry.OpenTelemetry`
  package *and* a one-time `OpenTelemetryBackendRegistration.Register()` call
  before setup. This is a harder gate than Python's extras or TypeScript's peer
  dependencies: the core package deliberately names no OpenTelemetry type, so
  adding the dependency alone changes nothing until the backend factory is
  registered. Everything the fail-open row describes —
  `PROVIDE_EXPORTER_*_FAIL_OPEN` degrading a failed provider build to fallback
  without setting the provider flag — lives in `OpenTelemetryBackend.Install*`
  and therefore lives behind that same gate.
- Gauge semantics: Python tracks per-attribute-set values and exposes the
  aggregate in-process `value` as the sum across all attribute sets
  (`src/provide/telemetry/metrics/fallback.py`). TypeScript, Go, Rust, and C#
  follow the OTel-native last-reading model — `value` returns the most recent
  value written, regardless of attribute set. The OTel-exported metric stream
  is consistent across all five languages (per-series last reading); only the
  in-process `.value()` accessor differs. Cross-language comparisons of the
  aggregate accessor are not supported.
- ASGI/HTTP middleware: only Python ships a pre-built request-lifecycle
  middleware, `provide.telemetry.asgi.TelemetryMiddleware`
  (`src/provide/telemetry/asgi/middleware.py`). TypeScript, Go, Rust and C#
  do not; their READMEs show the manual pattern instead — extract W3C context
  via `extractW3CContext()` / `ExtractW3CContext()` / `extract_w3c_context()`,
  bind it with the language's context helpers at request start, and clear it
  at request end.
- Pretty log rendering: Python, TypeScript, Go, and Rust honour
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
  **C# does not have this renderer.** `PROVIDE_LOG_FORMAT=pretty` is accepted
  and produces a distinct output — `Logger.Render` quotes the values, where
  `console` leaves them bare — but it emits no ANSI, does not consult whether
  stderr is a TTY, and does not honour `PROVIDE_LOG_PRETTY_FIELDS`. The
  `LoggingConfig.PrettyKeyColor` / `PrettyValueColor` / `PrettyFields`
  properties used to exist on the C# config object and be copied by `Clone()`
  while nothing populated them and no renderer read them. They are gone:
  `spec/telemetry-api.yaml` scopes `PROVIDE_LOG_PRETTY_*` to Python,
  TypeScript, Go and Rust, so a C# caller could set them and change nothing.
  An absent property is honest; a present one that is ignored reads as
  support.
- Metrics fallback export: when no OTel backend is installed, fallback
  counter/gauge/histogram state accumulates in-process and is dropped at
  shutdown — identically in all five languages. (This entry previously
  claimed Python flushes a stderr JSON snapshot during `shutdown_telemetry()`;
  no such flush exists in `src/provide/telemetry/metrics/fallback.py` or
  anywhere in the package's history — the claim described code that never
  shipped.) The uniform drop is the contract: a caller who needs the final
  values reads the instruments or `get_health_snapshot()` before shutting
  down.
