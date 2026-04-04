// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// Package telemetry provides a batteries-included observability SDK for Go.
// It mirrors the provide-telemetry Python and TypeScript implementations with
// the same processor chain: context merge → standard fields → trace IDs →
// sampling → schema → PII → emit.
//
// Quick start:
//
//	cfg, err := telemetry.SetupTelemetry()
//	if err != nil {
//	    log.Fatal(err)
//	}
//	defer telemetry.ShutdownTelemetry(context.Background())
//
//	logger := telemetry.GetLogger(ctx, "my.service")
//	logger.Info("my.service.started.ok")
//
// # Public API surface
//
// All symbols listed below correspond to the canonical entries in
// spec/telemetry-api.yaml, with names converted to Go PascalCase.
//
// ## Lifecycle
//   - [SetupTelemetry] — idempotent initialisation from environment variables
//   - [ShutdownTelemetry] — flush and tear down all subsystems
//
// ## Logging
//   - [GetLogger] — return a named *slog.Logger with the full processor chain
//   - [Logger] — package-level default *slog.Logger (set by SetupTelemetry)
//   - [BindContext] / [UnbindContext] / [ClearContext] — per-request field binding
//   - [GetBoundFields] — read current context fields
//   - [BindSessionContext] / [GetSessionID] / [ClearSessionContext]
//   - [LevelTrace] — custom slog level below DEBUG
//   - [IsDebugEnabled] / [IsTraceEnabled]
//
// ## Tracing
//   - [GetTracer] — return the package-level Tracer (OTel or no-op)
//   - [DefaultTracer] — package-level Tracer instance (the "tracer" instance in spec)
//   - [Trace] — run fn inside a span (the idiomatic Go equivalent of the trace decorator)
//   - [GetTraceContext] / [SetTraceContext]
//
// ## Metrics
//   - [GetMeter] — return the OTel meter (nil when OTel is unavailable)
//   - [NewCounter] / [NewGauge] / [NewHistogram] — idiomatic Go constructors
//     (spec names counter/gauge/histogram; Go convention uses New prefix)
//
// ## Propagation
//   - [ExtractW3CContext] / [BindPropagationContext] / [GetPropagationContext]
//
// ## Sampling
//   - [GetSamplingPolicy] / [SetSamplingPolicy] / [ShouldSample]
//
// ## Backpressure
//   - [GetQueuePolicy] / [SetQueuePolicy]
//   - [TryAcquire] / [Release]
//
// ## Resilience
//   - [GetExporterPolicy] / [SetExporterPolicy]
//   - [RunWithResilience]
//
// ## Cardinality
//   - [GetCardinalityLimits] — return all registered limits
//   - [RegisterCardinalityLimit] — register or update a limit for a key
//   - [ClearCardinalityLimits] — remove all registered limits
//   - [GuardAttributes] — apply limits to an attribute map
//
// ## PII
//   - [GetPIIRules] — return all current rules
//   - [RegisterPIIRule] — append a single rule
//   - [ReplacePIIRules] — replace all rules atomically
//   - [SanitizePayload]
//
// ## Health
//   - [GetHealthSnapshot]
//
// ## Schema
//   - [Event] — build and validate a structured DA(R)S event name
//   - [EventName] — validate and return a dot-joined event name from segments
//   - [ValidateEventName] — validate a pre-built dotted name string
//
// ## SLO
//   - [ClassifyError] / [RecordREDMetrics] / [RecordUSEMetrics]
//
// ## Runtime
//   - [GetRuntimeConfig] / [UpdateRuntimeConfig]
//   - [ReloadRuntimeFromEnv] / [ReconfigureTelemetry]
//
// ## Errors
//   - [TelemetryError] / [ConfigurationError] / [EventSchemaError]
//
// ## Types
//   - [SamplingPolicy] / [QueuePolicy] / [ExporterPolicy]
//   - [CardinalityLimit] / [PIIRule] / [HealthSnapshot]
//   - [TelemetryConfig] / [Span] / [Tracer] / [Counter] / [Gauge] / [Histogram]
//
// ## Config helpers
//   - [ConfigFromEnv] / [DefaultTelemetryConfig]
package telemetry

// Event builds and validates a structured DA(R)S event name from segments and
// returns it as a plain string. It is the Go equivalent of the spec's event()
// function that returns a structured event value.
//
// The DA(R)S pattern requires 3–5 dot-separated lowercase segments:
//
//	domain.action.status                  (3 segments)
//	domain.action.resource.status         (4 segments)
//	domain.action.resource.detail.status  (5 segments)
//
// Returns an *EventSchemaError if the segments are invalid.
func Event(segments ...string) (string, error) {
	return EventName(segments...)
}

// RegisterCardinalityLimit registers or updates the cardinality limit for key.
// It is the spec-named equivalent of [SetCardinalityLimit].
func RegisterCardinalityLimit(key string, limit CardinalityLimit) {
	SetCardinalityLimit(key, limit)
}

// GetCardinalityLimits returns a snapshot of all currently registered
// cardinality limits, keyed by attribute name.
func GetCardinalityLimits() map[string]CardinalityLimit {
	_cardinalityMu.RLock()
	defer _cardinalityMu.RUnlock()
	cp := make(map[string]CardinalityLimit, len(_cardinalityLimits))
	for k, v := range _cardinalityLimits {
		cp[k] = v
	}
	return cp
}

// ClearCardinalityLimits removes all registered cardinality limits and their
// associated caches. It is the exported equivalent of _resetCardinalityLimits.
func ClearCardinalityLimits() {
	_resetCardinalityLimits()
}

// RegisterPIIRule appends a single PIIRule to the global rule list.
// It is the spec-named equivalent — [ReplacePIIRules] replaces all rules atomically.
func RegisterPIIRule(rule PIIRule) {
	_piiMu.Lock()
	defer _piiMu.Unlock()
	_piiRules = append(_piiRules, rule)
}

// ReplacePIIRules atomically replaces all PII rules with the provided slice.
// It is the spec-named equivalent of [SetPIIRules].
func ReplacePIIRules(rules []PIIRule) {
	SetPIIRules(rules)
}
