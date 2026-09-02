# Go Changelog

All notable changes to `github.com/provide-io/provide-telemetry/go`.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **`PROVIDE_LOG_INCLUDE_CALLER` and `PROVIDE_LOG_CODE_ATTRIBUTES` do something.**
  Both were parsed into `LoggingConfig` and read by nothing: `AddSource` and
  `slog.SourceKey` appeared nowhere in the package, so no record ever carried a
  filename or a line number while the spec declared both variables applicable to
  Go and `INCLUDE_CALLER` defaulted on.

  `INCLUDE_CALLER` emits `filename` — the base name, never the absolute path
  `runtime.Frame` carries, which is the path the *compiling* machine had —
  and `lineno`, on every renderer and on the exported record.
  `CODE_ATTRIBUTES` emits `code.file.path`, `code.function.name` and
  `code.line.number` on the exported record only, which is what the knob
  promises: these carry the full path, and printing that locally is the leak
  `filename` reports a base name to avoid. The gates are independent.

  `filename`/`lineno` are attached in the telemetry handler rather than through
  `slog.HandlerOptions{AddSource: true}`. `AddSource` emits a `source` group of
  `{function, file, line}`, which is not the canonical shape, and it reaches only
  the JSON and text renderers — the pretty renderer builds no `HandlerOptions`
  and the OTLP log bridge is a sibling handler, so both would have been left
  without a callsite. The `code.*` attributes are attached by a thin handler
  wrapping the bridge, which is what keeps them off the local renderers.

  The record's `PC` is captured by `slog.Logger.log` before any handler runs and
  survives every rebuild in the chain, so the frame is the caller's without any
  frame-skipping.

  Cost, since `INCLUDE_CALLER` defaults on: one `runtime.CallersFrames` lookup
  and a record rebuild per emitted record — the same lookup stdlib `AddSource`
  does. `BenchmarkLogEmit_WithCallsite` and `BenchmarkLogEmit_WithoutCallsite`
  measure it against each other; they are also the first benchmarks in this
  package to cover the emit path at all, which is why the knob could be given a
  default of on without any gate pricing it.

### Fixed

- **The PII pass dropped duplicate attribute keys and randomized attribute
  order.** Sanitizing converts a record's attributes to a `map[string]any`, runs
  the rule engine, and converts back — and a Go map cannot represent two things
  slog guarantees.

  Duplicate keys collapsed. slog permits them and leaves rendering to the
  handler, so `logger.Info("m", slog.String("k", "a"), slog.String("k", "b"))` is
  legitimate; keying a map by name meant the last write won and `"a"` was gone,
  with nothing reporting it. Anything accumulating a repeated field in a loop
  lost all but the final one.

  Order was randomized, because Go deliberately randomizes map iteration. Six
  emissions of one identical call produced six orders — irrelevant to a JSON
  consumer, and visible churn for the `console` and `pretty` renderers, for
  anyone diffing log files, and for golden-output tests.

  The handler now keeps the attributes as an ordered slice and passes maps only
  as arguments, sanitizing in rounds — one per occurrence of a repeated key, so
  every duplicate is judged by the engine under its own key rather than smuggled
  past it. Almost every record takes exactly one round. The engine is untouched:
  `SanitizePayload` remains the cross-language contract the fixtures pin, and
  splitting one map into several changes no decision it makes, because
  `SanitizeMap` judges each entry on its own key, path and value and no rule
  consults a sibling.

  Keys are cleaned before the split, not after. Hardening strips control
  characters from keys — a newline in one used to forge a second log line
  through the pretty renderer — so the engine returns them under the cleaned
  name, and a rebuild keyed on the caller's original spelling would have found
  nothing and dropped exactly the attributes that most need to survive.

- **ANSI is emitted to a Windows console only once it can render it.** A console
  handle is a character device, so the terminal probe said colour was fine on
  every one of them — including legacy conhost, which prints `←[36m` literally.
  Setup enables `ENABLE_VIRTUAL_TERMINAL_PROCESSING`, and whether that succeeded
  is now the answer to "does this terminal render ANSI"; before setup, and where
  enabling fails, colour is off. Behaviour away from Windows is unchanged, down
  to a pretty logger built before `SetupTelemetry` still being coloured.

  Exercised against a real console screen buffer: the test allocates one, writes
  a record through the whole SDK and reads the cells back. A `bytes.Buffer`
  cannot see any of this, and no CI job has a console at all, because GitHub
  Actions redirects every stream to a pipe.

  **The console's output code page is deliberately not touched**, and finding
  that out is what those tests were worth. The code page decides how a console
  decodes the bytes written to it, and is not UTF-8 by default — but Go never
  writes bytes to a console: `os.File` classifies a console handle as
  `kindConsole`, and `internal/poll`'s `writeConsole` decodes the UTF-8, encodes
  UTF-16 and calls `WriteConsoleW`. An earlier version of this change set the
  code page, on the assumption that Go wrote raw bytes as C# does; the console
  test disproved it by rendering a non-ASCII record correctly on CP437. Two
  tests now hold that shape in place — one writes straight to the handle on
  CP437 and requires the output to be correct, so a future Go release that
  stopped using `WriteConsoleW` would say so, and one requires that setup leaves
  the host's code page exactly where it found it.

### Fixed

- **A log record the destination refuses is counted as an export failure.**
  `log/slog` discards whatever a handler returns, so a writer that fails — a
  pipe whose reader exited, a full disk, a closed file, a dropped network sink —
  lost every record silently while `GetHealthSnapshot().LogsEmitted` kept
  climbing. The SDK's own self-observability asserted a delivery that never
  happened. `WithLogOutput` makes an arbitrary destination ordinary, so a
  failing one is no longer exotic.

  The failure lands in `LogsExportFailures`, the canonical bucket for an export
  attempt that returned an error. `LogsDropped` is reserved for records refused
  *before* export — by consent, sampling or backpressure — and a record must
  never count as both emitted and dropped. `LogsEmitted` keeps its meaning:
  incremented once per record that passes the admission gates.

- **The package logger keeps exporting to OTLP after a reconfigure.** The log
  bridge was attached only during setup, by `_wireBackendBindingsLocked`. Every
  reload path — `ReconfigureTelemetry`, `UpdateRuntimeConfig`,
  `ReloadRuntimeFromEnv` — rebuilds the handler chain through
  `_configureLogger`, which built a bare renderer with no bridge. So after any
  reconfigure, `Logger()` and `slog.Default()` silently stopped reaching the
  collector while the config still reported the endpoint as enabled.
  `GetLogger(ctx, name)` was unaffected: it attaches the bridge itself.

  The cause was three independent constructions of the same chain, two of which
  drifted. There is now one — `_baseHandlerWithBridge` — and all three sites
  call it, so a reload cannot produce a chain that differs from the one setup
  installed.

- **Attributes bound with `logger.With(...)` are sanitized, validated, and
  rendered.** `WithAttrs` handed them to the base handler as well as recording
  them, and the base handler formats what it is given straight to the output —
  so bound attributes reached the log past both the PII engine and schema
  validation. A credential bound once at a request boundary appeared in the
  clear on every subsequent record:

  ```go
  logger.Info("rec", "password", "hunter2")              // "password":"***"
  logger.With("password", "hunter2").Info("rec")         // "password":"hunter2"
  ```

  Bound attributes now join the record before any processor runs, so one code
  path sees everything. The same fix resolves the mirror defect in schema
  validation, where a required key satisfied via `With` still produced
  `_schema_error`.

  Of the five SDKs this affected Go alone. Python folds `.bind()` into the same
  `event_dict` every processor reads, TypeScript re-parses pino's serialized
  line before redacting, and Rust and C# have no per-logger binding API — only
  the context helpers, which are merged ahead of PII.

- **A `slog.Group` passed as a record attribute keeps its contents.** The
  processor chain converts attributes to a map and back, and took
  `Value.Any()` on a group — which returns `[]slog.Attr`. The PII engine walks
  `map[string]any` and `[]any`, so it could not see inside; and the JSON
  renderer serialized the exported half of each `Attr`, so
  `slog.Group("g", slog.String("password", "hunter2"))` rendered as
  `"g":[{"Key":"password","Value":{}}]` — every value destroyed, redacted or
  not. Groups round-trip as nested maps now, which both renders them correctly
  and lets sanitization reach inside them.

- **Fields this SDK adds stay at the top level.** `service.name`,
  `service.env`, `service.version`, `trace.id` and `span.id` were appended
  after a caller's `WithGroup` had been delegated to the base handler, so they
  landed inside the caller's group. An empty group is elided again, as slog
  specifies.

### Added

- **`WithLogOutput(w io.Writer)` selects where rendered log records go.** All
  three renderers — `console`, `json` and `pretty` — write to it:

  ```go
  _, err := telemetry.SetupTelemetry(telemetry.WithLogOutput(sink))
  ```

  This is the surface a host needs to wrap the SDK's log stream — to prefix it
  when several language runtimes share one stream, to tee it, or to drop it.

  A writer is a handle rather than a string, so no environment variable names
  it and it is not part of `TelemetryConfig`; it sits beside
  `WithTracerProvider`, `WithMeterProvider` and `WithLoggerProvider`. Keeping
  it out of the config is what makes it durable: `ReconfigureTelemetry`,
  `UpdateRuntimeConfig` and `ReloadRuntimeFromEnv` all rebuild the handler
  chain from a config, and a writer that is not in one cannot be dropped by any
  of them. It is installed for the life of the runtime; change the destination
  by shutting down and setting up again.

  The option carries three guarantees. Writes are serialized, so the writer
  need not be safe for concurrent use even though `GetLogger` builds a handler
  per call. `ShutdownTelemetry` calls `Flush() error` when the writer has one,
  so a `bufio.Writer` keeps its tail. A nil writer — including a nil pointer
  inside a non-nil interface, which passes an ordinary nil check and would
  panic on the first record — is a `ConfigurationError`.

  Pretty-format colors follow the destination: an `*os.File` is probed for a
  terminal, and any other writer is asked, getting colors only if it implements
  `IsTerminal() bool`.

  Root-package equivalents for the names that lived only in `go/logger`:

  | `go/logger` | Root package |
  |---|---|
  | `Configure(LogConfig{...})` | `SetupTelemetry(WithConfig(cfg))` |
  | `LogConfig` | `TelemetryConfig` / `LoggingConfig` |
  | `DefaultLogConfig()` | `DefaultTelemetryConfig()` |
  | `GetDefaultLogger()` | `GetLogger(ctx, name)` |
  | `IsEnabled(level)` | `slog.Logger.Enabled(ctx, level)`, or `IsDebugEnabled()` / `IsTraceEnabled()` |
  | `NewNullLogger()` | `SetupTelemetry(WithLogOutput(io.Discard))` |
  | `NewBufferLogger()` | `SetupTelemetry(WithLogOutput(&bytes.Buffer{}))` |

  `GetLogger(ctx, name)` rather than `Logger()`: `Logger()` returns nil before
  setup, and it carries no logger name, so `PROVIDE_LOG_MODULE_LEVELS` stops
  matching. `io.Discard` silences the rendered stream only — a configured OTLP
  logs exporter is a separate sink and keeps shipping records until
  `PROVIDE_LOG_OTLP_ENABLED=false`.

## [0.8.1] — 2026-08-22

### Breaking

- **The `go/logger` package is removed.** `github.com/provide-io/provide-telemetry/go/logger`
  duplicated the root package's API (`GetLogger`, `EventName`, PII rules, error
  fingerprinting, schema validation) behind a second import path, was imported
  by nothing in the repository, and was the one surface that skipped the root
  package's `init`-time PII hash canonicaliser — a binary linking only
  `go/logger` hashed non-string values with `%v` rather than RFC 8785 canonical
  JSON. Import the root package instead:
  `telemetry "github.com/provide-io/provide-telemetry/go"`. The ten names that
  existed only in `go/logger` (`Configure`, `DefaultLogConfig`,
  `GetDefaultLogger`, `IsEnabled`, `NewBufferLogger`, `NewNullLogger`,
  `ResetPIIRules`, `ResetSecretPatterns`, `SetSamplingFunc`,
  `SetSanitizePayloadFunc`) were test helpers and hooks with no root-package
  equivalent. Its gremlins step and the two `ci-go.yml` coverage steps — gated
  on a `go/logger/go.mod` that never existed, so they had silently never run —
  go with it.

- **`PROVIDE_CONSENT_LEVEL` fails closed on a value it does not recognise.**
  `LoadConsentFromEnv` — called by `SetupTelemetry` and by the lazy pre-setup
  `GetLogger` path — sets consent to `ConsentNone` when the variable is set,
  non-empty and not one of `FULL`, `FUNCTIONAL`, `MINIMAL`, `NONE` (trimmed,
  case-insensitive), and writes one warning per process to `os.Stderr` naming
  the raw value: `[provide-telemetry] PROVIDE_CONSENT_LEVEL="NOEN" is not one
  of FULL, FUNCTIONAL, MINIMAL, NONE; consent set to NONE (fail-closed)`. The
  warning goes to stderr directly rather than through `Logger()`, which the
  `NONE` it just applied would silence. It used to ignore the value and leave
  the current level in place, so a misspelled opt-out in an otherwise untouched
  process kept collecting at `FULL`. Unset and blank (empty or whitespace-only)
  remain no-ops. `ResetConsentForTests` also re-arms the warning. The
  `consent_env_invalid_fails_closed` runtime probe pins it cross-language.

## [0.8.0] — 2026-08-19

### Breaking

- **`PROVIDE_LOG_LEVEL=CRITICAL` now excludes `ERROR` records.** `_parseLevel`
  folded `CRITICAL` onto `slog.LevelError`, so a CRITICAL threshold admitted
  ERROR — while `consent.go`'s own table ranked CRITICAL above ERROR, meaning a
  single record was ranked one way for filtering and another for consent.
  CRITICAL now has a level of its own, `LevelCritical`. Applies to
  `PROVIDE_LOG_MODULE_LEVELS` entries too.

- **The `level` field on a record is now the canonical spelling.** slog renders
  a level it has no name for by arithmetic on the nearest one it does, so
  `LevelTrace` reached the wire as `"DEBUG-4"` and `LevelCritical` as
  `"ERROR+4"` — values no level table anywhere recognises, and CRITICAL is
  reachable through the ordinary `Log(ctx, ParseLevel(s), msg)` path. The
  handler now renders through `LevelName`.

### Added

- `ParseLevel(string) slog.Level` and `LevelName(slog.Level) string`, exported
  from both the root package and `go/logger`. Go needed no new logging door —
  `slog.Logger.Log(ctx, level, msg, args...)` already is one — only the
  conversion that every adapter was re-implementing.
- `LevelCritical`, continuing slog's ladder at the same pitch above `ERROR`.
- `go/internal/levelcore`, the canonical ladder shared by the root package and
  `go/logger`, with its own gremlins surface in CI; without it the root step's
  `internal/` exclusion would have left the new package mutated by nothing.

### Fixed

- `normalizeLevel` accepts `WARN` and `FATAL`, which it rejected while Rust
  accepted both. The caller's own spelling is still what gets stored.
- Consent ranks through the one shared table. `FATAL` used to be unrecognised
  there and was dropped as if it were the least severe record in the ladder.

## [0.7.2] — 2026-08-16

### Fixed

- **Secret redaction kept only the first match in a value.** A string
  carrying two credentials lost the first and emitted the second intact.
  A filesystem path earlier in the string could also shield a genuine
  credential behind it, because the path exemption was applied to the
  first match and then abandoned the whole value. Every pattern now runs
  across the whole value, each match is judged on its own token, and the
  surviving spans are merged and replaced right to left.

## [0.7.0] — 2026-08-14

### Changed

- **BREAKING: `telemetry.Logger` is now `telemetry.Logger()`**, with
  `SetLogger()` as the write half. The variable could not be both publicly
  assignable and race-free: `_configureLogger` reassigned it on every setup
  and reconfiguration while `GetLogger` read it, and the `go/otel` module
  assigned it from another package. Both halves now go through one atomic.
  The 13 examples that called `telemetry.Logger.Error` on the setup-failure
  path — precisely when no logger exists — use stdlib `slog` there instead.
- **BREAKING: `EnableReceipts` takes a `ReceiptOptions` struct** — the old
  `(bool, string, string)` form could not express a sink or return an error,
  and enabling receipts without a sink is now an error rather than signing
  one per redaction and discarding it. `original_hash` is SHA-256 over
  RFC 8785 canonical JSON rather than `fmt.Sprintf("%v")` (which collapsed
  the number `1` and the string `"1"` to one digest); all seven vectors in
  `spec/receipt_fixtures.yaml` reproduce byte-for-byte. `HealthSnapshot`
  gains `ReceiptFailures` (25 → 26 fields, breaks exhaustive literals), and
  the receipt timestamp is fixed-width `2006-01-02T15:04:05.000Z` instead of
  `RFC3339Nano`, which trims trailing zeros and formats one instant to
  varying widths.
- **BREAKING: `ReconfigureResult` converges on the cross-language shape** —
  `applied`/`previous`/`current`/`state`/`error`, dropping the `status` field
  that always duplicated `state`, with JSON tags so it round-trips with the
  other SDKs' output.
- **`_incAsyncBlockingRisk` is deleted.** Go has no event loop and no runtime
  predicate to detect one — a goroutine parked in `FlushTelemetry` costs one
  goroutine and blocks nothing — so the three `async_blocking_risk` counters
  are pinned at zero by a real setup/emit/flush/shutdown test, and the fields
  stay only as cross-language contract.

### Fixed

- **OTLP-exported log records now pass through the telemetry pipeline.** The
  OTel log bridge was a sibling of the telemetry handler rather than
  downstream of it, so every exported record bypassed consent, schema
  validation, sampling, backpressure, hardening and PII redaction — a
  password masked locally left the process in the clear on the bridge.
- **Typed values are hardened.** PII traversal handled exactly
  `map[string]any` and `[]any`; a `[]credentials`, a `map[string]string` or a
  plain struct carried its `Password` field to the log verbatim. Hardening
  now normalizes reflectively (string-keyed maps, exported struct fields by
  JSON name, arrays/slices in order), collapses cycles and repeated
  references to `"***"`, and `SecurityConfig`'s three caps — previously
  parsed, validated and read by nothing — now bound log attributes.
- **Runtime state is published as immutable generations.** Reconfiguration
  previously wrote hot config blocks through the same pointer every live
  `slog` handler retained — six `-race` reports across the read paths. A
  generation (config plus the logger built from it) is now swapped under one
  atomic store and never written again.
- **Baggage keys are RFC 7230 tokens.** An inbound baggage key became a
  log-attribute key verbatim, and a newline in a key let a remote caller
  fabricate a log record. `ParseBaggage` rejects non-token keys and strips
  control characters from values; `HardenInput` hardens keys as well as
  values.
- **`tracestate` is validated against the W3C list-member grammar** — one bad
  member (CRLF, control characters, missing `=`, oversized key) discards the
  whole header instead of forwarding it.
- **Facade defects:** `UpdateConfig` discarded its config and returned nil;
  `Reconfigure` dropped config/options/context and re-read the environment;
  `Flush` collapsed one aggregate error onto all three signals and now
  reports `NotOwned` — never `Flushed` — for a backend without a flush
  interface; `ProviderImmutableError` is a distinct type rather than an alias
  of `ConfigurationError` (its `As` method keeps legacy matches working).

## [0.6.1] — 2026-07-30

No functional change. `go` and `go/otel` are identical to 0.6.0 apart from the
version files and the `go/otel` requirement below.

### Fixed

- **Re-tagged so a direct-VCS fetch resolves.** The repository's history was
  rewritten to strip commit trailers, which moved the commits that `go/v0.6.0`
  and `go/otel/v0.6.0` pointed at. `sum.golang.org` is append-only, so it still
  holds the hashes built from the original commits: fetching `v0.6.0` through
  the module proxy keeps working from its cache, but a fetch that bypasses the
  proxy (`GOPROXY=direct`) rebuilds the zip from the new commit and fails
  verification. 0.6.1 is tagged on the rewritten history and hashes cleanly by
  either route. Use it instead of 0.6.0.

### Changed

- `go/otel` now requires `github.com/provide-io/provide-telemetry/go v0.6.1`.

---

## [0.6.0] — 2026-07-29

### Added

- **`FlushTelemetry(ctx)`** — drain without teardown. `ShutdownTelemetry` was the only way to force records out and it tears the providers down; flush force-flushes every provider we installed and leaves them installed and usable. Deadline handling matches shutdown (`PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS` when `ctx` carries none), with one deliberate difference: an expired deadline is returned, not suppressed, because a caller flushing to be sure its records are out needs to learn when they were not. A lone failure is returned unwrapped, so `err == context.DeadlineExceeded` matches.
- **Adoption of a host application's OTel providers** — the facade used a provider only when one was handed in via `BackendSetupState`. It now adopts `otel.GetTracerProvider()` / `GetMeterProvider()` for any signal where it installed nothing itself, duck-typed on the `ForceFlush`/`Shutdown` pair so the API's delegating placeholder is not mistaken for a live SDK provider. Adoption never implies ownership: `ShutdownTelemetry` drops the reference without tearing the host's SDK down, and `FlushTelemetry` does not drain it. The global is probed per span rather than snapshotted at setup, so an auto-instrumentation agent or lazily-initialised vendor distro that registers later is picked up.
- **`WithConfig(*TelemetryConfig)`** — `SetupTelemetry(WithConfig(cfg))` takes an in-memory config instead of reading the process environment. For hosts that re-exec or fork and must not mutate `os.Environ`.
- **`SetDefaultTracer(t Tracer)`** — replaces the package-level tracer. See the removal note below.

### Changed

- **`DefaultTracer` is no longer an exported variable.** It is read from every traced call and written during setup and shutdown, and a two-word interface value read while it is being written can tear into a stale itab paired with a new data pointer. The binding is now an atomic reached through `GetTracer(name)` and replaced through the new `SetDefaultTracer(t)`. Migration: read `GetTracer("")`, write `SetDefaultTracer(t)`.
- **`ShutdownTelemetry` no longer switches off a host's instrumentation.** It reset the OTel globals to no-ops unconditionally, so tearing our telemetry down also unregistered a provider the host had installed. Only globals this module registered are reset.
- **Signal enablement is read live, not snapshotted.** `TracingEnabled()` / `MetricsEnabled()` are exported for the OTel backend and answer from an atomic gate published whenever the runtime config changes. They default to enabled before `SetupTelemetry` and after `ShutdownTelemetry`, matching what `Trace()` has always done — so a host that installs its own SDK and never calls setup still has its provider adopted.
- **`GetRuntimeStatus().Providers` reports what the emit path would do**, which now includes a host-installed provider, while `Signals` continues to report configured intent. A signal reads as fallback only once a *loaded* config switches it off.

### Fixed

- **Shutdown drains the three signals concurrently.** They shared one context deadline in sequence, so a stalled traces exporter consumed the whole budget and queued metrics and log records were dropped without an export attempt. Same fix `FlushTelemetry` already had; both now run through one drain path.
- **No lock is held across a drain.** `FlushTelemetry` held `_setupMu` for its whole duration and every `Trace()` and metric call takes that same mutex, so a slow collector stalled the process for the deadline. It snapshots under the lock and drains outside it. Separately, the OTel backend's `Shutdown` no longer holds its provider lock across the drain, which would otherwise block a concurrent flush on a mutex no context deadline can bound.
- **No data race on the per-span provider lookup.** Resolving the tracer per span moved reads of setup-time globals onto the hot path while setup and shutdown wrote them. The instrumentation-scope name and the tracer binding are atomic; the backend's provider globals have their own `RWMutex`.
- **`FlushTelemetry`'s godoc is its own.** The declaration sat directly under `ShutdownTelemetry`'s comment block with no blank line, so `go doc` attributed shutdown's contract to flush and left `ShutdownTelemetry` undocumented.
- **SDK-level trace sampling is real.** The default `TracerProvider` is built with `ParentBased(TraceIDRatioBased(min(sampling.TracesRate, Tracing.SampleRate)))`. Previously the rate gated only the facade while the global tracer and instrumentations sampled everything.

### Removed

- **The `go/tracer` package.** A standalone parallel copy of the tracer machinery that nothing imported, carrying its own unsynchronized exported global. Its CI test and mutation steps were guarded on `hashFiles('go/tracer/go.mod')` and that module file never existed, so they had never run. Use the root `telemetry` package: `GetTracer`, `SetDefaultTracer`, `Trace`.

## [0.5.1] — 2026-07-10

### Added

- Coverage-guided fuzz targets for `parseOTLPHeaders`, `maskEndpointURL`, `validateRate`, `_validatedSignalEndpointURL`, and env-float→rate validation (`go test -fuzz` / `make fuzz`).
- Local OSS-Fuzz helper recipe under `infra/oss-fuzz/` + `scripts/oss-fuzz-local.sh` (local Docker only).

### Fixed

- `validateRate` now rejects NaN and Inf (not only out-of-range finite values).

## [0.4.3] — 2026-04-24

### API Alignment

- **Backpressure tickets** — `TryAcquire(signal)` returns a `*QueueTicket`; pass that exact ticket to `Release(ticket)`. This keeps release ownership tied to the queue slot that was acquired.

### Reliability

- **Disabled tracing/metrics gates** — disabled signals no longer install OTel providers or emit through local wrappers.
- **Lazy logger sampling** — environment log sampling is applied before explicit setup.
- **OTLP shared endpoint expansion** — the optional OTel module resolves shared OTLP endpoints to the correct per-signal `/v1/*` paths.

### Quality

- Added regression coverage for ticket release, disabled tracing/metrics, lazy sampling, and shared OTLP endpoint resolution.

---

## [0.2.4] — 2026-04-08

### Features

- **`RegisterSecretPattern`** — register custom secret detection patterns with name-based deduplication
- **Benchmark suite** — `benchmark_test.go` with 13 `testing.B` benchmarks; `make bench` target
- **Stress tests** — `scripts/stress/main.go` with 6 scenarios (logging, sampling, PII, backpressure, metrics, tracing)

### Bug Fixes

- **Health tracking double-count** — `TryAcquire` no longer increments `emitted_*` (was double-counting with `ShouldSample`)
- **`export_latency_ms` always 0** — wired `_recordExportLatencyForSignal` into `RunWithResilience` on success
- **`validateRuntimeOverrides` cyclomatic complexity** — extracted sub-validators to reduce complexity from 17 → 8

---

## [0.2.3] — 2026-04-06

### Features

- **`StrictSchema` in `RuntimeOverrides`** — `StrictSchema *bool` field added; hot-reloadable via `UpdateRuntimeConfig`

### Improvements

- **`UpdateRuntimeConfig` input validation** — rates validated to `[0, 1]`; sizes, retries, and backoff/timeout floats validated non-negative and finite; matches Python/TypeScript behaviour

### Bug Fixes

- **CI: gosec submodule exclusion** — `cmd/e2e_cross_language_client` excluded from gosec scan (separate module requiring Go 1.26); fixes failures on Dependabot action-bump PRs

---

## [0.2.2] — 2026-04-06

### Features

- **Control-plane integrity** — `RuntimeOverrides` struct for hot-field-only updates; `UpdateRuntimeConfig` narrows signature to accept `RuntimeOverrides` (not full `TelemetryConfig`); `ReloadRuntimeFromEnv` re-reads env vars at runtime and warns on cold-field drift; `ReconfigureTelemetry` for full restart
- **Data governance** — `classification.go`: `ClassificationPolicy`, `RegisterClassificationRules`, `GetClassificationPolicy`, `SetClassificationPolicy`; `consent.go`: `ConsentLevel`, `SetConsentLevel`, `GetConsentLevel`, `ShouldAllow`, `LoadConsentFromEnv`; `receipts.go`: cryptographic redaction receipts with optional HMAC signing.
- **Config masking** — `TelemetryConfig.String()` / `GoString()` / `RedactedString()` mask OTLP header values and endpoint passwords so configs are safe to log
- **PII depth control** — `PROVIDE_LOG_PII_MAX_DEPTH` env var; default max depth changed from 32 to 8; `SanitizePayload` respects depth limit across all rule types and secret detection

### Improvements

- **Canonical 25-field `HealthSnapshot`** — per-signal fields (`LogsEmitted`, `LogsDropped`, `LogsExportFailures`, `LogsRetries`, `LogsExportLatencyMs`, `LogsAsyncBlockingRisk`, `LogsCircuitState`, `LogsCircuitOpenCount` × 3 signals) plus `SetupError`; aligned with Python and TypeScript
- **Sampling signal validation** — `SetSamplingPolicy`, `GetSamplingPolicy`, `ShouldSample` return errors for unknown signals; parity with Python/TypeScript
- **Backpressure unlimited** — default `LogsMaxSize`/`TracesMaxSize`/`MetricsMaxSize` is `0` (unlimited); `TryAcquire` treats `<= 0` as unlimited
- **Cardinality clamping** — `SetCardinalityLimit` clamps `MaxValues` to min 1 and `TTLSeconds` to min 1.0
- **OTLP header `+` preservation** — `+` characters in OTLP header values are preserved (not decoded as spaces); parity with Python/TypeScript
- **Event name strict mode** — 3–5 segment enforcement always on; format validation gated behind `PROVIDE_TELEMETRY_STRICT_SCHEMA`

### CI / Quality

- `golangci-lint` v2 with full linter suite (`errcheck`, `exhaustive`, `gocyclo`, `unused`, `gosec`, `revive`)
- `gosec` security scanning
- `govulncheck` vulnerability scanning
- `gremlins` mutation testing at 100% efficacy threshold
- 100% statement coverage enforced on every push
- `-race` flag on all test runs

---

## [0.2.0] — 2026-04-01

### Initial Go Implementation

Full Go implementation of the provide-telemetry API surface, conforming to `spec/telemetry-api.yaml`.

- **Core setup** — `SetupTelemetry()`, `ShutdownTelemetry()`, `DefaultTelemetryConfig()`, `ConfigFromEnv()`
- **Structured logging** — `Logger` (`*slog.Logger`), `BindContext()`, `BindSessionContext()`, `EventName()` / `event()` helper, `EventSchema` validation
- **Tracing** — `StartSpan()`, `EndSpan()`, OTel `TracerProvider` with OTLP gRPC/HTTP export
- **Metrics** — `Counter()`, `Gauge()`, `Histogram()`, OTel `MeterProvider` with OTLP export; RED/USE SLO helpers (`IncrementRequest`, `IncrementError`, `RecordLatency`)
- **Sampling** — `SetSamplingPolicy()`, `GetSamplingPolicy()`, `ShouldSample()` with per-key overrides
- **Backpressure** — `SetQueuePolicy()`, `GetQueuePolicy()`, bounded ticket-based queues per signal
- **Resilience** — `SetExporterPolicy()`, `GetExporterPolicy()`, retry with exponential backoff, timeout, circuit breaker, executor pool
- **PII sanitization** — `RegisterPIIRule()`, `SanitizePayload()`, 17 default sensitive keys, secret pattern detection (AWS, JWT, GitHub tokens, etc.)
- **Cardinality guard** — `SetCardinalityLimit()`, `GetCardinalityLimit()`, TTL-based attribute eviction
- **Health** — `GetHealthSnapshot()`
- **Propagation** — `ExtractW3CContext()`, `InjectW3CHeaders()` with size guards
- **Runtime** — `GetRuntimeConfig()`, `UpdateRuntimeConfig()`, `ReloadRuntimeFromEnv()`, `ReconfigureTelemetry()`
- **Context** — `GetTraceID()`, `GetSpanID()`, `GetSessionID()`
- **Testing** — `ResetForTests()`, `resetSetupState()` helpers; `testing.go` test isolation utilities
