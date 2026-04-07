# Go Changelog

All notable changes to `github.com/provide-io/provide-telemetry/go`.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
