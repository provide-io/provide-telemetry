// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"fmt"
	"log/slog"
	"maps"
	"strings"
	"sync/atomic"
)

// GetRuntimeConfig returns the active TelemetryConfig, or nil if SetupTelemetry has not
// been called (or the system has been shut down).
func GetRuntimeConfig() *TelemetryConfig {
	_setupMu.Lock()
	defer _setupMu.Unlock()
	if _runtimeCfg == nil {
		return nil
	}
	return cloneTelemetryConfig(_runtimeCfg)
}

// _signalGate answers "should this signal be emitting right now" without taking
// _setupMu: the OTel backend is asked for Providers() from inside
// _wireBackendBindingsLocked, which already holds it, and from the per-span
// path, which must not contend on it.
//
// The state is stored inverted so the zero value — no SetupTelemetry yet —
// reads as enabled, with no init() to keep in step. Every caller works in
// positive terms; the inversion lives here alone.
type _signalGate struct{ off atomic.Bool }

func (g *_signalGate) Enabled() bool    { return !g.off.Load() }
func (g *_signalGate) Set(enabled bool) { g.off.Store(!enabled) }

// Published under _setupMu by _publishRuntimeGatesLocked at every point
// _runtimeCfg changes.
var (
	_tracingGate _signalGate //nolint:gochecknoglobals
	_metricsGate _signalGate //nolint:gochecknoglobals
)

// TracingEnabled reports whether the facade should be using a tracer provider
// right now: no loaded config has switched tracing off.
//
// This is the per-span reader as well as the gate the optional OTel backend
// uses to decide whether to adopt a provider — one predicate, because those are
// the same question. Read live rather than snapshotted during backend Setup,
// because Setup does not always run — _setupBackendLocked skips it on the
// endpoint-less path, which is exactly the pure-adoption case — and because a
// snapshot cleared by Shutdown had no way back.
//
// Defaults to true before SetupTelemetry and after ShutdownTelemetry, matching
// the emit path: Trace() runs without a config, so a host application that
// installs its own SDK on the OTel globals and never calls SetupTelemetry must
// still have that provider adopted. Requiring _setupDone here instead would
// start those spans on the no-op tracer and drop them silently.
func TracingEnabled() bool { return _tracingGate.Enabled() }

// MetricsEnabled is the metrics counterpart of TracingEnabled.
func MetricsEnabled() bool { return _metricsGate.Enabled() }

func _publishRuntimeGatesLocked() {
	_tracingGate.Set(_runtimeCfg == nil || _runtimeCfg.Tracing.Enabled)
	_metricsGate.Set(_runtimeCfg == nil || _runtimeCfg.Metrics.Enabled)
}

func _runtimeSetupDone() bool {
	_setupMu.Lock()
	defer _setupMu.Unlock()
	return _setupDone
}

// UpdateRuntimeConfig applies the given hot-reloadable overrides atomically.
// Nil pointer fields in RuntimeOverrides are left unchanged.
// Returns an error if the telemetry system is not set up.
func UpdateRuntimeConfig(overrides RuntimeOverrides) error {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if !_setupDone || _runtimeCfg == nil {
		return fmt.Errorf("telemetry not set up: call SetupTelemetry first")
	}

	if err := validateRuntimeOverrides(overrides); err != nil {
		return err
	}
	next := cloneTelemetryConfig(_runtimeCfg)
	applyRuntimeOverrides(next, overrides)
	_applyRuntimePolicies(next)
	_publishGenerationLocked(next)
	return nil
}

// ReloadRuntimeFromEnv re-parses all environment variables, applies only hot-reloadable
// fields, and preserves the live cold/provider config. No subsystems are restarted; use
// ReconfigureTelemetry for a full restart. Cold fields (ServiceName, Environment, Version,
// Tracing.Enabled, Metrics.Enabled) that have drifted from the current config are logged
// as warnings.
func ReloadRuntimeFromEnv() error {
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if !_setupDone {
		return fmt.Errorf("telemetry not set up: call SetupTelemetry first")
	}

	cfg, err := ConfigFromEnv()
	if err != nil {
		return err
	}

	// Warn on cold-field drift.
	_warnColdFieldDrift(cfg)

	// The logging overrides below carry the OTLP fields baked into an installed
	// log exporter. Applying a drifted endpoint would leave records exporting to
	// the old collector while GetRuntimeConfig reported the new one — so with a
	// live log provider this is an error, not a warning, matching Python's
	// reload path. Identity/enable drift above stays a warning: those fields are
	// never applied by this function.
	if _providerStatusLocked().Logs && _loggerFieldsChanged(_runtimeCfg, cfg) {
		return _providerConfigError()
	}

	overrides := runtimeOverridesFromConfig(cfg)
	next := cloneTelemetryConfig(_runtimeCfg)
	applyRuntimeOverrides(next, overrides)
	_applyRuntimePolicies(next)
	_publishGenerationLocked(next)
	return nil
}

// rejectProviderChangingFields reports an error when cfg's provider-changing
// fields differ from the live runtime config while a live provider is
// installed.
//
// These are the fields baked into a provider at install time: service identity
// (which becomes the Resource), the per-signal OTLP endpoints and headers, and
// the enable flags. UpdateRuntimeConfig applies its overrides to the live
// config without touching installed providers, so letting one of these through
// produces a config that describes an exporter nothing is using — and, worse,
// makes the next ReconfigureTelemetry compare new-against-new and never report
// that a restart is required.
//
// The liveness gate is the same one ReconfigureTelemetry uses: with no live
// provider there is nothing an exporter has baked in, so a differing field is
// not an error — the two facade methods must not disagree on the same input.
func rejectProviderChangingFields(cfg *TelemetryConfig) error {
	_setupMu.Lock()
	defer _setupMu.Unlock()
	current := _runtimeCfg
	if current == nil {
		return nil
	}
	providers := _providerStatusLocked()
	if _providerConfigChanged(current, cfg, providers.Traces, providers.Metrics, providers.Logs) {
		return _providerConfigError()
	}
	return nil
}

// validateReconfigureTarget checks a caller-supplied reconfiguration target.
//
// validateTelemetryConfig covers rates and log format/level; the hot-reloadable
// blocks (backpressure sizes, exporter policy, security limits) are checked by
// the same validators UpdateRuntimeConfig runs, so a config accepted by one
// entry point is accepted by the other.
func validateReconfigureTarget(cfg *TelemetryConfig) error {
	if err := validateTelemetryConfig(cfg); err != nil {
		return err
	}
	return validateRuntimeOverrides(runtimeOverridesFromConfig(cfg))
}

func runtimeOverridesFromConfig(cfg *TelemetryConfig) RuntimeOverrides {
	return RuntimeOverrides{
		Sampling:     &cfg.Sampling,
		Backpressure: &cfg.Backpressure,
		Exporter:     &cfg.Exporter,
		Security:     &cfg.Security,
		SLO:          &cfg.SLO,
		EventSchema:  &cfg.EventSchema,
		PIIMaxDepth:  &cfg.Logging.PIIMaxDepth,
		StrictSchema: &cfg.StrictSchema,
		Logging:      &cfg.Logging,
	}
}

func applyRuntimeOverrides(cfg *TelemetryConfig, overrides RuntimeOverrides) {
	// Logging is applied first so per-field scalar overrides below
	// (PIIMaxDepth) take precedence when both are supplied.
	//
	// The reference-typed fields are cloned rather than shared. `cfg.Logging =
	// *overrides.Logging` is a shallow struct copy, so without this the live
	// runtime config would hold the very maps the caller still owns — and a
	// caller mutating its own cfg.Logging.ModuleLevels while any goroutine
	// emits a log record trips Go's `fatal error: concurrent map read and map
	// write`, which is unrecoverable.
	if overrides.Logging != nil {
		cfg.Logging = *overrides.Logging
		cfg.Logging.OTLPHeaders = maps.Clone(overrides.Logging.OTLPHeaders)
		cfg.Logging.ModuleLevels = maps.Clone(overrides.Logging.ModuleLevels)
		cfg.Logging.PrettyFields = append([]string(nil), overrides.Logging.PrettyFields...)
	}
	if overrides.Sampling != nil {
		cfg.Sampling = *overrides.Sampling
	}
	if overrides.Backpressure != nil {
		cfg.Backpressure = *overrides.Backpressure
	}
	if overrides.Exporter != nil {
		cfg.Exporter = *overrides.Exporter
	}
	if overrides.Security != nil {
		cfg.Security = *overrides.Security
	}
	if overrides.SLO != nil {
		cfg.SLO = *overrides.SLO
	}
	if overrides.EventSchema != nil {
		cfg.EventSchema = *overrides.EventSchema
		cfg.EventSchema.RequiredKeys = append([]string(nil), overrides.EventSchema.RequiredKeys...)
	}
	if overrides.PIIMaxDepth != nil {
		cfg.Logging.PIIMaxDepth = *overrides.PIIMaxDepth
	}
	if overrides.StrictSchema != nil {
		cfg.StrictSchema = *overrides.StrictSchema
	}
}

// _warnColdFieldDrift logs a warning if cold fields in next differ from the live config.
func _warnColdFieldDrift(next *TelemetryConfig) {
	if _runtimeCfg != nil {
		_checkColdDrift(next)
	}
}

func _checkColdDrift(next *TelemetryConfig) {
	var drifted []string
	if next.ServiceName != _runtimeCfg.ServiceName {
		drifted = append(drifted, "ServiceName")
	}
	if next.Environment != _runtimeCfg.Environment {
		drifted = append(drifted, "Environment")
	}
	if next.Version != _runtimeCfg.Version {
		drifted = append(drifted, "Version")
	}
	if next.Tracing.Enabled != _runtimeCfg.Tracing.Enabled {
		drifted = append(drifted, "Tracing.Enabled")
	}
	if next.Metrics.Enabled != _runtimeCfg.Metrics.Enabled {
		drifted = append(drifted, "Metrics.Enabled")
	}
	if logger := Logger(); len(drifted) > 0 && logger != nil {
		logger.Warn("runtime.cold_field_drift",
			slog.String("fields", strings.Join(drifted, ",")),
			slog.String("action", "restart required to apply"),
		)
	}
}

// ReconfigureTelemetry applies hot-reloadable config changes from the current
// environment, or from an explicit config when the caller passes WithConfig.
// If provider-changing fields (service identity, endpoints, enable flags) differ AND real
// OTel providers are installed, it returns a ConfigurationError instead of silently
// restarting — matching the Python/TypeScript/Rust contract.
// Callers who truly need a provider restart should call ShutdownTelemetry then SetupTelemetry.
func ReconfigureTelemetry(ctx context.Context, opts ...SetupOption) (*TelemetryConfig, error) {
	_ = ctx // reserved for future use (e.g. shutdown context propagation)
	_setupMu.Lock()
	defer _setupMu.Unlock()

	if !_setupDone || _runtimeCfg == nil {
		return nil, NewConfigurationError("telemetry not set up: call SetupTelemetry first")
	}

	// Apply functional options to interpret caller intent. WithConfig supplies an
	// explicit target and suppresses the environment read, matching SetupTelemetry.
	state := &_setupState{}
	for _, fn := range opts {
		fn(state)
	}

	// Rejected before anything is touched, exactly as at setup: a reconfigure
	// that fails must leave the runtime — writer included — where it found it.
	if err := _validateLogOutputOption(state); err != nil {
		return nil, err
	}

	target, err := _reconfigureTarget(state)
	if err != nil {
		return nil, err
	}

	providers := _providerStatusLocked()
	if _providerConfigChanged(_runtimeCfg, target, providers.Traces, providers.Metrics, providers.Logs) {
		return nil, _providerConfigError()
	}

	// Apply only hot-reloadable fields, preserving cold/provider config — onto a
	// clone, never through the published pointer. Every live slog handler holds
	// the published *TelemetryConfig, so writing through it raced with each
	// handler's read of Logging.Level, Logging.ModuleLevels and EventSchema.
	next := cloneTelemetryConfig(_runtimeCfg)
	_applyHotFields(next, target)
	_applyRuntimePolicies(next)
	_moveLogOutputLocked(state)
	_publishGenerationLocked(next)
	return cloneTelemetryConfig(next), nil
}

// _validateLogOutputOption rejects a WithLogOutput carrying no writer.
//
// Checked before any state moves so a reconfigure that fails leaves the
// runtime, writer included, exactly where it found it.
func _validateLogOutputOption(state *_setupState) error {
	if state.logOutputSet && _writerIsNil(state.logOutput) {
		return NewConfigurationError("WithLogOutput: writer is nil")
	}
	return nil
}

// _reconfigureTarget resolves the config a reconfigure is aiming at: the
// caller's when WithConfig supplied one, the environment otherwise.
//
// The env path validates as it parses; an in-memory config from WithConfig has
// had nothing check it. Without that check a NaN sampling rate clamps to 0.0
// and silently stops the signal, and a negative queue size becomes an unbounded
// queue — both reported as a successful reconfigure. SetupTelemetry(WithConfig)
// and UpdateRuntimeConfig both reject these; the two facade methods on one
// runtime must not disagree.
func _reconfigureTarget(state *_setupState) (*TelemetryConfig, error) {
	if state.config == nil {
		return ConfigFromEnv()
	}
	if err := validateReconfigureTarget(state.config); err != nil {
		return nil, err
	}
	return state.config, nil
}

// _moveLogOutputLocked points rendered records at a destination the caller
// asked for.
//
// The destination moves only when the caller asks. Absent means unchanged, not
// cleared: a host reloading its log level must not have its records quietly
// returned to os.Stderr. Console first, then the sink — the sink decides at
// install whether its destination renders ANSI, and on Windows that answer
// depends on virtual-terminal processing already being on.
//
// Called with _setupMu held.
func _moveLogOutputLocked(state *_setupState) {
	if !state.logOutputSet {
		return
	}
	_ = _flushLogSink()
	_prepareLogConsole(state.logOutput)
	_installLogSink(state.logOutput)
}

// _providerConfigChanged returns true when reconfiguration would require
// reinstalling at least one live OTel provider. tracerLive/meterLive/loggerLive
// reflect which signal providers are currently installed; signal-specific fields
// are only checked when the corresponding provider is live. Decomposed into
// per-signal helpers to keep cyclomatic complexity below the lint threshold.
func _providerConfigChanged(current, target *TelemetryConfig, tracerLive, meterLive, loggerLive bool) bool {
	if !tracerLive && !meterLive && !loggerLive {
		return false
	}
	if _identityFieldsChanged(current, target) {
		return true
	}
	if tracerLive && _tracerFieldsChanged(current, target) {
		return true
	}
	if meterLive && _meterFieldsChanged(current, target) {
		return true
	}
	return loggerLive && _loggerFieldsChanged(current, target)
}

// _identityFieldsChanged reports whether service name/env/version differ.
// These are baked into every provider's Resource, so a change forces all
// live providers to be reinstalled.
func _identityFieldsChanged(current, target *TelemetryConfig) bool {
	return current.ServiceName != target.ServiceName ||
		current.Environment != target.Environment ||
		current.Version != target.Version
}

func _tracerFieldsChanged(current, target *TelemetryConfig) bool {
	return current.Tracing.Enabled != target.Tracing.Enabled ||
		current.Tracing.OTLPEndpoint != target.Tracing.OTLPEndpoint ||
		!maps.Equal(current.Tracing.OTLPHeaders, target.Tracing.OTLPHeaders)
}

func _meterFieldsChanged(current, target *TelemetryConfig) bool {
	return current.Metrics.Enabled != target.Metrics.Enabled ||
		current.Metrics.OTLPEndpoint != target.Metrics.OTLPEndpoint ||
		!maps.Equal(current.Metrics.OTLPHeaders, target.Metrics.OTLPHeaders)
}

func _loggerFieldsChanged(current, target *TelemetryConfig) bool {
	return current.Logging.OTLPEndpoint != target.Logging.OTLPEndpoint ||
		current.Logging.OTLPEnabled != target.Logging.OTLPEnabled ||
		!maps.Equal(current.Logging.OTLPHeaders, target.Logging.OTLPHeaders)
}

func _applyHotFields(current, fresh *TelemetryConfig) {
	current.Sampling = fresh.Sampling
	current.Backpressure = fresh.Backpressure
	current.Exporter = fresh.Exporter
	current.Security = fresh.Security
	current.SLO = fresh.SLO
	current.StrictSchema = fresh.StrictSchema
	current.EventSchema = fresh.EventSchema
	// Logging is hot except the fields baked into an installed log exporter:
	// the OTLP endpoint, headers, and enable flag keep their live values.
	// Everything else — level, format, renderer options — must apply, or
	// Reconfigure validates a level change and then silently discards it while
	// UpdateConfig on the same runtime applies it.
	//
	// The log destination is not here to be lost: WithLogOutput keeps it out of
	// the config entirely (see logger_sink.go).
	baked := current.Logging
	current.Logging = fresh.Logging
	current.Logging.OTLPEndpoint = baked.OTLPEndpoint
	current.Logging.OTLPEnabled = baked.OTLPEnabled
	current.Logging.OTLPHeaders = baked.OTLPHeaders
	// Cloned, not aliased: `fresh` can be a caller-supplied config (WithConfig),
	// and sharing these with the live runtime hands a caller the ability to
	// mutate it concurrently with the emit path. See applyRuntimeOverrides.
	current.EventSchema.RequiredKeys = append([]string(nil), fresh.EventSchema.RequiredKeys...)
	current.Logging.ModuleLevels = maps.Clone(fresh.Logging.ModuleLevels)
	current.Logging.PrettyFields = append([]string(nil), fresh.Logging.PrettyFields...)
}
