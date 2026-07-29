# Go Changelog

All notable changes to `github.com/provide-io/provide-telemetry/go`.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
- **Data governance** — `classification.go`: `ClassificationPolicy`, `RegisterClassificationRules`, `GetClassificationPolicy`, `SetClassificationPolicy`; `consent.go`: `ConsentLevel`, `SetConsentLevel`, `GetConsentLevel`, `ShouldAllow`, `LoadConsentFromEnv`; `receipts.go`: cryptographic redaction receipts with optional HMAC signing (strippable module)
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
