# Go Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full `provide-telemetry` API surface in Go, passing `spec/validate_conformance.py` and sharing major.minor from `VERSION`.

**Architecture:** stdlib-first (`log/slog`, `context.Context`), stable Go OTel SDK (1.x) as optional dependency via interfaces. Each subsystem in its own file mirroring the Python/TypeScript structure. All 56 required API symbols from `spec/telemetry-api.yaml` must be exported.

**Tech Stack:** Go 1.22+, `log/slog` (stdlib), `go.opentelemetry.io/otel` v1.35+, `github.com/sony/gobreaker`, `github.com/cenkalti/backoff/v4`, `github.com/hashicorp/golang-lru/v2`

---

## Dependency Rationale

| Package | Version | Role | Why this one |
|---------|---------|------|-------------|
| `log/slog` (stdlib) | Go 1.21+ | Structured logging | Stdlib — zero dependency, universal adoption, `Handler` interface for processor composition |
| `context.Context` (stdlib) | — | Per-request context propagation | Go convention — explicit `ctx` threading, goroutine-safe |
| `go.opentelemetry.io/otel` | v1.35+ | OTel API (traces, metrics) | **Stable 1.x** — GA for traces, metrics, and logs. Actively maintained by CNCF. |
| `go.opentelemetry.io/otel/sdk` | v1.35+ | TracerProvider, MeterProvider | Official SDK, stable API surface |
| `go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp` | v1.35+ | OTLP trace export | Official HTTP OTLP exporter |
| `go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp` | v1.35+ | OTLP metrics export | Official HTTP OTLP exporter |
| `go.opentelemetry.io/otel/propagation` | v1.35+ | W3C traceparent/tracestate | Built-in `TraceContext` propagator |
| `go.opentelemetry.io/otel/bridge/otelslog` | v0.11+ | slog → OTel log bridge | Official bridge, maps slog records to OTel log records |
| `github.com/sony/gobreaker` | v1.0+ | Circuit breaker | 3K+ stars, production-grade (Sony), well-tested. Better than building custom. |
| `github.com/cenkalti/backoff/v4` | v4.3+ | Exponential backoff with jitter | 5K+ stars, mature, supports context cancellation |
| `github.com/hashicorp/golang-lru/v2` | v2.0+ | TTL-expiring LRU cache | 4K+ stars, HashiCorp maintained, `expirable.NewLRU` for cardinality guards |
| `golang.org/x/time/rate` | latest | Token bucket rate limiter | stdlib-adjacent, for backpressure queue limiting |

### Not using (and why)

| Package | Why skipped |
|---------|------------|
| `github.com/rs/zerolog` | Faster than slog but non-standard. slog is stdlib and every library speaks it. |
| `go.uber.org/zap` | Great library but slog replaced the need for it. Adding zap means users must bridge. |
| `github.com/sirupsen/logrus` | Effectively deprecated — author recommends slog. |

---

## File Structure

```
go/
├── go.mod                    # module github.com/provide-io/provide-telemetry/go
├── go.sum
├── VERSION                   # "0.4.2" — synced with root VERSION
├── telemetry.go              # Public API facade (all exported symbols)
├── config.go                 # TelemetryConfig, env var parsing
├── config_test.go
├── setup.go                  # SetupTelemetry/ShutdownTelemetry, sync.Mutex lifecycle
├── setup_test.go
├── logger.go                 # slog Handler chain, GetLogger, Logger instance
├── logger_test.go
├── context.go                # BindContext, UnbindContext, ClearContext (context.Context wrappers)
├── context_test.go
├── session.go                # BindSessionContext, GetSessionID, ClearSessionContext
├── session_test.go
├── tracing.go                # GetTracer, Tracer instance, Trace wrapper, context
├── tracing_test.go
├── metrics.go                # Counter, Gauge, Histogram, GetMeter, fallback impls
├── metrics_test.go
├── propagation.go            # ExtractW3CContext, BindPropagationContext
├── propagation_test.go
├── sampling.go               # SamplingPolicy, SetSamplingPolicy, ShouldSample
├── sampling_test.go
├── backpressure.go           # QueuePolicy, ticket-based bounded queue
├── backpressure_test.go
├── resilience.go             # ExporterPolicy, RunWithResilience, circuit breaker
├── resilience_test.go
├── pii.go                    # PIIRule, RegisterPIIRule, SanitizePayload
├── pii_test.go
├── cardinality.go            # CardinalityLimit, GuardAttributes
├── cardinality_test.go
├── health.go                 # HealthSnapshot, GetHealthSnapshot
├── health_test.go
├── schema.go                 # EventName validation
├── schema_test.go
├── slo.go                    # ClassifyError, RecordREDMetrics, RecordUSEMetrics (optional)
├── slo_test.go
├── runtime.go                # GetRuntimeConfig, UpdateRuntimeConfig, ReloadRuntimeFromEnv
├── runtime_test.go
├── errors.go                 # TelemetryError, ConfigurationError, EventSchemaError
├── errors_test.go
├── otel.go                   # OTel provider setup (build-tag gated or interface-based)
├── otel_test.go
├── testing.go                # Test helpers, state reset functions
└── README.md
```

---

## Design Decisions

### OTel as optional dependency

Go doesn't have Cargo-style conditional compilation. Two approaches:

**Option A: Interface-based DI (recommended)**
```go
// telemetry.go
type TracerProvider interface { ... }
type MeterProvider interface { ... }

// Default no-op implementations are used unless user calls:
func WithTracerProvider(tp TracerProvider) Option { ... }
func WithMeterProvider(mp MeterProvider) Option { ... }
```

Users who want OTel pass it at setup:
```go
import "go.opentelemetry.io/otel/sdk/trace"
tp := trace.NewTracerProvider(...)
telemetry.SetupTelemetry(telemetry.WithTracerProvider(tp))
```

**Option B: Build tags**
```go
//go:build otel
```

Option A is more idiomatic Go and doesn't require build-tag coordination.

### Context propagation

Go threads `context.Context` explicitly. The library stores per-request state via `context.WithValue()`:

```go
func BindContext(ctx context.Context, fields map[string]any) context.Context
func GetBoundFields(ctx context.Context) map[string]any
```

The slog `Handler` reads these fields from the context automatically.

### Processor chain via slog Handler middleware

```go
// Each processor is a Handler that wraps the next Handler:
type processorHandler struct {
    next slog.Handler
    fn   func(ctx context.Context, r *slog.Record) bool // return false to drop
}
```

Chain: `merge_context → add_standard_fields → apply_sampling → enforce_schema → sanitize_pii → renderer`

### Error types

```go
type TelemetryError struct { msg string; cause error }
type ConfigurationError struct { TelemetryError }
type EventSchemaError struct { TelemetryError }

// All implement error interface. ConfigurationError also wraps like ValueError:
func (e *ConfigurationError) Unwrap() error { return e.cause }
```

---

## Task Breakdown

### Task 1: Project scaffold + config

**Files:** Create: `go/go.mod`, `go/VERSION`, `go/config.go`, `go/config_test.go`, `go/errors.go`, `go/errors_test.go`

- [ ] Initialize `go.mod` with `module github.com/provide-io/provide-telemetry/go`, Go 1.22
- [ ] Create `VERSION` file with `0.4.2`
- [ ] Implement `TelemetryConfig` struct with all fields from `config_env_vars` in spec
- [ ] Implement `ConfigFromEnv()` parsing all `PROVIDE_*` and `OTEL_*` env vars
- [ ] Implement error types: `TelemetryError`, `ConfigurationError`, `EventSchemaError`
- [ ] Write tests for config parsing, defaults, validation
- [ ] Commit

### Task 2: Health + schema

**Files:** Create: `go/health.go`, `go/health_test.go`, `go/schema.go`, `go/schema_test.go`

- [ ] Implement `HealthSnapshot` struct with all 25 per-signal fields
- [ ] Implement `GetHealthSnapshot()` with `sync.Mutex`-protected counters
- [ ] Implement internal counter increment functions (exported for internal use)
- [ ] Implement `EventName(*segments)` with strict/relaxed mode
- [ ] Write tests including boundary cases (0 segments, 6 segments, uppercase in strict mode)
- [ ] Commit

### Task 3: Context + session

**Files:** Create: `go/context.go`, `go/context_test.go`, `go/session.go`, `go/session_test.go`

- [ ] Define context keys using unexported `type contextKey struct{}`
- [ ] Implement `BindContext(ctx, fields) context.Context`
- [ ] Implement `UnbindContext(ctx, keys...) context.Context`
- [ ] Implement `ClearContext(ctx) context.Context`
- [ ] Implement `BindSessionContext(ctx, sessionID) context.Context`
- [ ] Implement `GetSessionID(ctx) string`
- [ ] Implement `ClearSessionContext(ctx) context.Context`
- [ ] Write tests verifying context isolation across goroutines
- [ ] Commit

### Task 4: Sampling

**Files:** Create: `go/sampling.go`, `go/sampling_test.go`

- [ ] Implement `SamplingPolicy` struct (DefaultRate float64, Overrides map[string]float64)
- [ ] Implement `SetSamplingPolicy(signal, policy)`, `GetSamplingPolicy(signal)` with `sync.RWMutex`
- [ ] Implement `ShouldSample(signal, key)` with `math/rand` and fast-paths for rate 0.0/1.0
- [ ] Wire drop counter to health module
- [ ] Write tests including concurrency stress test
- [ ] Commit

### Task 5: Backpressure

**Files:** Create: `go/backpressure.go`, `go/backpressure_test.go`

- [ ] Implement `QueuePolicy` struct (LogsMaxSize, TracesMaxSize, MetricsMaxSize int)
- [ ] Implement ticket-based bounded queue using `chan struct{}` (buffered channel = natural semaphore)
- [ ] Implement `SetQueuePolicy`, `GetQueuePolicy`
- [ ] Implement `TryAcquire(signal) bool`, `Release(signal)`
- [ ] Wire to health counters
- [ ] Write tests
- [ ] Commit

### Task 6: Resilience

**Files:** Create: `go/resilience.go`, `go/resilience_test.go`

- [ ] Add `go get github.com/sony/gobreaker github.com/cenkalti/backoff/v4`
- [ ] Implement `ExporterPolicy` struct (Retries, BackoffSeconds, TimeoutSeconds, FailOpen, AllowBlockingInEventLoop)
- [ ] Implement `SetExporterPolicy(signal, policy)`, `GetExporterPolicy(signal)`
- [ ] Implement `RunWithResilience(ctx, signal, fn)` using gobreaker for circuit breaker, backoff for retry, `context.WithTimeout` for timeouts
- [ ] Per-signal gobreaker instances (isolation)
- [ ] Wire to health counters (retries, export failures, export latency, last error)
- [ ] Write tests including circuit breaker trip/half-open/reset cycle
- [ ] Commit

### Task 7: PII sanitization

**Files:** Create: `go/pii.go`, `go/pii_test.go`

- [ ] Implement `PIIRule` struct (Path []string, Mode string, TruncateTo int)
- [ ] Implement `RegisterPIIRule`, `ReplacePIIRules`, `GetPIIRules`
- [ ] Implement `SanitizePayload(payload map[string]any, enabled bool, maxDepth int) map[string]any`
- [ ] Rule matching with wildcard `*` segments
- [ ] Modes: drop, redact ("***"), hash (sha256[:12]), truncate
- [ ] Default sensitive key detection (password, token, authorization, api_key, secret — case-insensitive)
- [ ] Recursive traversal of nested maps and slices with depth limit (32)
- [ ] Write tests including nested structures, all modes, depth limit
- [ ] Commit

### Task 8: Cardinality guards

**Files:** Create: `go/cardinality.go`, `go/cardinality_test.go`

- [ ] Add `go get github.com/hashicorp/golang-lru/v2`
- [ ] Implement `CardinalityLimit` struct (MaxValues int, TTLSeconds float64)
- [ ] Implement `RegisterCardinalityLimit`, `GetCardinalityLimits`, `ClearCardinalityLimits`
- [ ] Implement `GuardAttributes(attrs map[string]string) map[string]string` using expirable LRU
- [ ] Overflow value: `"__overflow__"`
- [ ] Write tests including TTL expiry
- [ ] Commit

### Task 9: Logger (slog Handler chain)

**Files:** Create: `go/logger.go`, `go/logger_test.go`

- [ ] Implement custom `slog.Handler` that composes middleware processors
- [ ] Processor chain: merge context → add standard fields → apply sampling → enforce schema → sanitize PII → output handler
- [ ] `GetLogger(name)` returns `*slog.Logger` with the custom handler
- [ ] Package-level `Logger` var (lazy-initialized default)
- [ ] JSON and text output modes controlled by config
- [ ] Wire context fields from `context.Context` into log records
- [ ] Write tests
- [ ] Commit

### Task 10: Tracing

**Files:** Create: `go/tracing.go`, `go/tracing_test.go`

- [ ] Define `Tracer` interface and no-op implementation
- [ ] Implement `GetTracer(name)`, package-level `Tracer` var
- [ ] Implement `Trace(ctx, name, fn)` — wraps fn in a span (real or no-op)
- [ ] Implement `GetTraceContext(ctx)`, `SetTraceContext(ctx, traceID, spanID)`
- [ ] Store trace/span IDs in context.Context
- [ ] Write tests
- [ ] Commit

### Task 11: Metrics

**Files:** Create: `go/metrics.go`, `go/metrics_test.go`

- [ ] Define instrument interfaces and in-process fallback implementations
- [ ] `Counter(name, opts...)` — returns named counter (fallback: atomic int64)
- [ ] `Gauge(name, opts...)` — returns named gauge (fallback: atomic float64 via math.Float64bits)
- [ ] `Histogram(name, opts...)` — returns named histogram (fallback: append to slice)
- [ ] `GetMeter(name)` — returns OTel meter if available, nil otherwise
- [ ] Wire sampling and backpressure checks
- [ ] Write tests
- [ ] Commit

### Task 12: Propagation

**Files:** Create: `go/propagation.go`, `go/propagation_test.go`

- [ ] Implement `PropagationContext` struct (Traceparent, Tracestate, Baggage, TraceID, SpanID)
- [ ] Implement `ExtractW3CContext(headers http.Header) PropagationContext`
- [ ] Parse traceparent format: `00-{trace_id}-{span_id}-{flags}`
- [ ] Size guards: 512 byte max for traceparent/tracestate, 8192 for baggage, 32 max tracestate pairs
- [ ] Implement `BindPropagationContext(ctx, pc) context.Context`
- [ ] Write tests including boundary size tests
- [ ] Commit

### Task 13: Runtime + setup/shutdown

**Files:** Create: `go/runtime.go`, `go/runtime_test.go`, `go/setup.go`, `go/setup_test.go`

- [ ] Implement `SetupTelemetry(opts ...Option) (*TelemetryConfig, error)` with `sync.Mutex` guard
- [ ] Implement `ShutdownTelemetry(ctx context.Context) error`
- [ ] Implement `GetRuntimeConfig`, `UpdateRuntimeConfig`, `ReloadRuntimeFromEnv`, `ReconfigureTelemetry`
- [ ] Hot/cold config split (policies hot-reloadable, providers require restart)
- [ ] Write tests including concurrent setup/shutdown
- [ ] Commit

### Task 14: OTel integration

**Files:** Create: `go/otel.go`, `go/otel_test.go`

- [ ] Implement OTel provider setup via functional options
- [ ] `WithTracerProvider`, `WithMeterProvider` options
- [ ] Bridge slog → OTel logs via `otelslog`
- [ ] W3C propagation via `otel/propagation.TraceContext`
- [ ] Real tracer/meter wiring when providers are supplied
- [ ] Write tests (with and without OTel)
- [ ] Commit

### Task 15: SLO helpers (optional)

**Files:** Create: `go/slo.go`, `go/slo_test.go`

- [ ] Implement `ClassifyError(excName string, statusCode int) map[string]string`
- [ ] Implement `RecordREDMetrics(route, method string, statusCode int, durationMs float64)`
- [ ] Implement `RecordUSEMetrics(resource string, utilizationPercent int)`
- [ ] Write tests
- [ ] Commit

### Task 16: Public facade + testing helpers

**Files:** Create: `go/telemetry.go`, `go/testing.go`, `go/README.md`

- [ ] Create `telemetry.go` that re-exports all public symbols (verify against spec)
- [ ] Create `testing.go` with `ResetForTests()` functions
- [ ] Run `spec/validate_conformance.py` — must pass for Go
- [ ] Run `scripts/check_version_sync.py` — must pass
- [ ] Write README.md following typescript/README.md structure
- [ ] Commit

### Task 17: CI integration

**Files:** Modify: `.github/workflows/ci-go.yml` (new)

- [ ] Create Go CI workflow: `go test ./go/...`, `go vet`, `staticcheck`, `golangci-lint`
- [ ] Add to branch protection required checks
- [ ] Run full test suite, verify all pass
- [ ] Commit

---

## Verification

```bash
# Unit tests
cd go && go test -v -race -coverprofile=coverage.out ./...

# Coverage check
go tool cover -func=coverage.out | tail -1  # should be 100%

# Spec conformance
uv run python spec/validate_conformance.py

# Version sync
uv run python scripts/check_version_sync.py

# Vet + lint
go vet ./...
staticcheck ./...
```

---

## Key Go Idioms to Follow

1. **Accept interfaces, return structs** — function params use interfaces, return concrete types
2. **context.Context as first param** — every function that does I/O or needs request state
3. **Errors are values** — return `error`, wrap with `%w`, use `errors.Is`/`errors.As`
4. **No init() functions** — explicit `SetupTelemetry()` call instead
5. **sync.Mutex for shared state** — not channels (channels are for communication, mutexes for state)
6. **Table-driven tests** — `tests := []struct{ name string; ... }{ ... }`
7. **unexported by default** — only export what's in the spec
