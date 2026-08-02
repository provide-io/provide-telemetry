// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"math"
	"testing"
)

// UpdateConfig must not alias the caller's maps into the live runtime config.
// Sharing them lets a caller mutate its own config while a goroutine is
// emitting a record, which is Go's unrecoverable "concurrent map read and map
// write" fatal error, not a recoverable panic.
func TestUpdateConfig_DoesNotAliasCallerOwnedMaps(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	base := DefaultTelemetryConfig()
	base.ServiceName = "alias-probe"
	if _, err := SetupTelemetry(WithConfig(base)); err != nil {
		t.Fatalf("setup: %v", err)
	}

	caller := cloneTelemetryConfig(base)
	caller.Logging.ModuleLevels = map[string]string{"db": "INFO"}
	caller.Logging.PrettyFields = []string{"event"}
	caller.EventSchema.RequiredKeys = []string{"event"}

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.UpdateConfig(context.Background(), caller); err != nil {
		t.Fatalf("UpdateConfig: %v", err)
	}

	// Mutate the caller's own config, as an application legitimately may.
	caller.Logging.ModuleLevels["db"] = "DEBUG"
	caller.Logging.PrettyFields[0] = "mutated"
	caller.EventSchema.RequiredKeys[0] = "mutated"

	live := GetRuntimeConfig()
	if got := live.Logging.ModuleLevels["db"]; got != "INFO" {
		t.Fatalf("live ModuleLevels aliased the caller's map: got %q", got)
	}
	if got := live.Logging.PrettyFields[0]; got != "event" {
		t.Fatalf("live PrettyFields aliased the caller's slice: got %q", got)
	}
	if got := live.EventSchema.RequiredKeys[0]; got != "event" {
		t.Fatalf("live RequiredKeys aliased the caller's slice: got %q", got)
	}
}

// The doc says provider-changing fields are rejected. They have to actually be:
// UpdateRuntimeConfig does not reinstall exporters, so accepting a new endpoint
// leaves records going to the old collector while GetRuntimeConfig reports the
// new one — and makes the next Reconfigure compare new-against-new and never
// report that a restart is needed.
func TestUpdateConfig_RejectsProviderChangingFields(t *testing.T) {
	base := DefaultTelemetryConfig()
	base.ServiceName = "provider-fields"

	cases := map[string]func(cfg *TelemetryConfig){
		"logs endpoint":    func(cfg *TelemetryConfig) { cfg.Logging.OTLPEndpoint = "http://elsewhere:4318" },
		"logs headers":     func(cfg *TelemetryConfig) { cfg.Logging.OTLPHeaders = map[string]string{"k": "v"} },
		"traces endpoint":  func(cfg *TelemetryConfig) { cfg.Tracing.OTLPEndpoint = "http://elsewhere:4318" },
		"metrics endpoint": func(cfg *TelemetryConfig) { cfg.Metrics.OTLPEndpoint = "http://elsewhere:4318" },
		"service name":     func(cfg *TelemetryConfig) { cfg.ServiceName = "renamed" },
		"tracing enabled":  func(cfg *TelemetryConfig) { cfg.Tracing.Enabled = !cfg.Tracing.Enabled },
		"metrics enabled":  func(cfg *TelemetryConfig) { cfg.Metrics.Enabled = !cfg.Metrics.Enabled },
		"logs otlp flag":   func(cfg *TelemetryConfig) { cfg.Logging.OTLPEnabled = !cfg.Logging.OTLPEnabled },
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			resetSetupState(t)
			t.Cleanup(func() { resetSetupState(t) })
			if _, err := SetupTelemetry(WithConfig(base)); err != nil {
				t.Fatalf("setup: %v", err)
			}

			target := cloneTelemetryConfig(base)
			mutate(target)

			rt := NewTelemetryRuntime(context.Background())
			if _, err := rt.UpdateConfig(context.Background(), target); err == nil {
				t.Fatal("expected a provider-immutable error")
			}
			// Nothing may have leaked into the live config either.
			if live := GetRuntimeConfig(); live.ServiceName != base.ServiceName ||
				live.Logging.OTLPEndpoint != base.Logging.OTLPEndpoint {
				t.Fatal("a rejected update still mutated the live config")
			}
		})
	}
}

// Hot-reloadable fields must still go through.
func TestUpdateConfig_AcceptsHotFields(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	base := DefaultTelemetryConfig()
	base.ServiceName = "hot-fields"
	if _, err := SetupTelemetry(WithConfig(base)); err != nil {
		t.Fatalf("setup: %v", err)
	}

	target := cloneTelemetryConfig(base)
	target.Sampling.LogsRate = 0.25

	rt := NewTelemetryRuntime(context.Background())
	updated, err := rt.UpdateConfig(context.Background(), target)
	if err != nil {
		t.Fatalf("UpdateConfig: %v", err)
	}
	if updated.Sampling.LogsRate != 0.25 {
		t.Fatalf("hot field not applied: %v", updated.Sampling.LogsRate)
	}
}

// ReconfigureTelemetry's WithConfig branch has to validate what it is handed.
// The env branch validates as it parses; an in-memory config has had nothing
// check it, and both SetupTelemetry(WithConfig) and UpdateRuntimeConfig reject
// these values.
func TestReconfigureTelemetry_ValidatesAnExplicitConfig(t *testing.T) {
	cases := map[string]func(cfg *TelemetryConfig){
		"NaN logs rate":        func(cfg *TelemetryConfig) { cfg.Sampling.LogsRate = math.NaN() },
		"Inf traces rate":      func(cfg *TelemetryConfig) { cfg.Sampling.TracesRate = math.Inf(1) },
		"negative queue size":  func(cfg *TelemetryConfig) { cfg.Backpressure.LogsMaxSize = -1 },
		"negative retries":     func(cfg *TelemetryConfig) { cfg.Exporter.LogsRetries = -1 },
		"bad log level":        func(cfg *TelemetryConfig) { cfg.Logging.Level = "LOUD" },
		"negative attr length": func(cfg *TelemetryConfig) { cfg.Security.MaxAttrValueLength = -1 },
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			resetSetupState(t)
			t.Cleanup(func() { resetSetupState(t) })

			base := DefaultTelemetryConfig()
			base.ServiceName = "reconfigure-validation"
			if _, err := SetupTelemetry(WithConfig(base)); err != nil {
				t.Fatalf("setup: %v", err)
			}

			target := cloneTelemetryConfig(base)
			mutate(target)

			if _, err := ReconfigureTelemetry(context.Background(), WithConfig(target)); err == nil {
				t.Fatal("expected reconfigure to reject the invalid config")
			}
		})
	}
}

func TestReconfigureTelemetry_AcceptsAValidExplicitConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	base := DefaultTelemetryConfig()
	base.ServiceName = "reconfigure-valid"
	if _, err := SetupTelemetry(WithConfig(base)); err != nil {
		t.Fatalf("setup: %v", err)
	}

	target := cloneTelemetryConfig(base)
	target.Sampling.LogsRate = 0.5

	got, err := ReconfigureTelemetry(context.Background(), WithConfig(target))
	if err != nil {
		t.Fatalf("ReconfigureTelemetry: %v", err)
	}
	if got.Sampling.LogsRate != 0.5 {
		t.Fatalf("hot field not applied: %v", got.Sampling.LogsRate)
	}
}

// A runtime built with WithConfig must not silently fall back to the process
// environment on Reconfigure(ctx, nil) — WithConfig exists precisely for hosts
// that must not read it.
func TestRuntimeReconfigure_ForwardsConstructorOptions(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "constructor-opts"
	cfg.Sampling.TracesRate = 0.01

	rt := NewTelemetryRuntime(context.Background(), WithConfig(cfg))
	if _, err := rt.Start(context.Background()); err != nil {
		t.Fatalf("start: %v", err)
	}

	// The environment carries no PROVIDE_SAMPLING_TRACES_RATE, so falling
	// through to ConfigFromEnv would restore the 1.0 default.
	got, err := rt.Reconfigure(context.Background(), nil)
	if err != nil {
		t.Fatalf("Reconfigure: %v", err)
	}
	if got.Sampling.TracesRate != 0.01 {
		t.Fatalf("constructor config was dropped: TracesRate=%v", got.Sampling.TracesRate)
	}
}

// An explicit cfg still wins over the constructor's.
func TestRuntimeReconfigure_ExplicitConfigOverridesConstructor(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "constructor-opts"
	cfg.Sampling.TracesRate = 0.01

	rt := NewTelemetryRuntime(context.Background(), WithConfig(cfg))
	if _, err := rt.Start(context.Background()); err != nil {
		t.Fatalf("start: %v", err)
	}

	explicit := cloneTelemetryConfig(cfg)
	explicit.Sampling.TracesRate = 0.5

	got, err := rt.Reconfigure(context.Background(), explicit)
	if err != nil {
		t.Fatalf("Reconfigure: %v", err)
	}
	if got.Sampling.TracesRate != 0.5 {
		t.Fatalf("explicit config did not win: TracesRate=%v", got.Sampling.TracesRate)
	}
}

func TestUpdateConfig_RejectsNilConfig(t *testing.T) {
	rt := NewTelemetryRuntime(context.Background())
	_, err := rt.UpdateConfig(context.Background(), nil)
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Fatalf("expected ConfigurationError, got %v", err)
	}
}

// A backend that answers per signal, so one endpoint's failure is not reported
// on the other two.
type _perSignalFlushBackend struct {
	_fakeBackend
	results map[string]error
}

func (b *_perSignalFlushBackend) ForceFlush(context.Context) error {
	return _joinSignalErrors(b.results)
}

func (b *_perSignalFlushBackend) ForceFlushBySignal(context.Context) map[string]error {
	return b.results
}

func _installPerSignalBackend(t *testing.T, results map[string]error, providers SignalStatus) {
	t.Helper()
	backend := &_perSignalFlushBackend{results: results}
	backend.providers = providers
	previous, replaced := RegisterBackend("per-signal-flush", backend)
	t.Cleanup(func() {
		if replaced {
			RegisterBackend("per-signal-flush", previous)
		} else {
			UnregisterBackend("per-signal-flush")
		}
	})
}

// One unreachable collector must not be reported as a failure on the signals
// that drained. An operator acting on the aggregate re-emits or alerts on
// records that were already delivered.
func TestFlush_ReportsEachSignalOnItsOwn(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	logsErr := errors.New("logs collector unreachable")
	_installPerSignalBackend(t,
		map[string]error{SignalLogs: logsErr, SignalTraces: nil, SignalMetrics: nil},
		SignalStatus{Logs: true, Traces: true, Metrics: true},
	)

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start: %v", err)
	}

	result, err := rt.Flush(context.Background())
	if !errors.Is(err, logsErr) {
		t.Fatalf("expected the logs error to survive aggregation, got %v", err)
	}
	if !result.Logs.Failed {
		t.Fatalf("expected logs Failed, got %+v", result.Logs)
	}
	if !result.Traces.Flushed || result.Traces.Failed || result.Traces.TimedOut {
		t.Fatalf("a healthy traces drain must not inherit the logs failure: %+v", result.Traces)
	}
	if !result.Metrics.Flushed || result.Metrics.Failed || result.Metrics.TimedOut {
		t.Fatalf("a healthy metrics drain must not inherit the logs failure: %+v", result.Metrics)
	}
}

// A provider the host installed shows up in Providers but is not ours to drain.
// Reporting Flushed would say its records are out while they sit in the host's
// batch processor.
func TestFlush_ReportsNotOwnedForAHostProvider(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// Traces is reported installed but absent from the per-signal map: the
	// backend did not install it.
	_installPerSignalBackend(t,
		map[string]error{SignalLogs: nil, SignalMetrics: nil},
		SignalStatus{Logs: true, Traces: true, Metrics: true},
	)

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start: %v", err)
	}

	result, err := rt.Flush(context.Background())
	if err != nil {
		t.Fatalf("flush: %v", err)
	}
	if !result.Traces.NotOwned {
		t.Fatalf("expected traces NotOwned, got %+v", result.Traces)
	}
	if result.Traces.Flushed {
		t.Fatal("a provider we never installed must not report Flushed")
	}
	if !result.Logs.Flushed || !result.Metrics.Flushed {
		t.Fatalf("our own signals must still report Flushed: %+v", result)
	}
}

// An expired deadline is a timeout, not an unspecified failure.
func TestFlush_ReportsTimedOutForADeadline(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_installPerSignalBackend(t,
		map[string]error{SignalLogs: context.DeadlineExceeded, SignalTraces: nil, SignalMetrics: nil},
		SignalStatus{Logs: true, Traces: true, Metrics: true},
	)

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start: %v", err)
	}

	result, _ := rt.Flush(context.Background())
	if !result.Logs.TimedOut || result.Logs.Failed {
		t.Fatalf("expected logs TimedOut, got %+v", result.Logs)
	}
}

// A signal with no provider at all still reports NotInstalled, ahead of
// everything else.
func TestFlush_NotInstalledWinsOverNotOwned(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_installPerSignalBackend(t,
		map[string]error{SignalLogs: nil},
		SignalStatus{Logs: true},
	)

	rt := NewTelemetryRuntime(context.Background())
	if _, err := rt.Start(context.Background(), WithConfig(DefaultTelemetryConfig())); err != nil {
		t.Fatalf("start: %v", err)
	}

	result, _ := rt.Flush(context.Background())
	for name, sig := range map[string]SignalFlushResult{"traces": result.Traces, "metrics": result.Metrics} {
		if !sig.NotInstalled || sig.NotOwned {
			t.Fatalf("expected %s NotInstalled only, got %+v", name, sig)
		}
	}
}

// _joinSignalErrors hands a lone error back untouched so FlushTelemetry's
// documented `== context.DeadlineExceeded` still matches.
func TestJoinSignalErrors(t *testing.T) {
	if got := _joinSignalErrors(nil); got != nil {
		t.Fatalf("expected nil for no errors, got %v", got)
	}
	if got := _joinSignalErrors(map[string]error{SignalLogs: nil}); got != nil {
		t.Fatalf("expected nil for a clean drain, got %v", got)
	}
	lone := errors.New("only one")
	if got := _joinSignalErrors(map[string]error{SignalLogs: lone, SignalTraces: nil}); got != lone { //nolint:errorlint
		t.Fatalf("a lone error must be handed back untouched, got %v", got)
	}
	first, second := errors.New("a"), errors.New("b")
	joined := _joinSignalErrors(map[string]error{SignalLogs: first, SignalTraces: second})
	if !errors.Is(joined, first) || !errors.Is(joined, second) {
		t.Fatalf("both errors must survive the join, got %v", joined)
	}
}

// Before SetupTelemetry the flush entry points short-circuit and drain nothing,
// so a provider a host put on the OTel globals is visible in Providers but
// untouched. Reporting it Flushed tells a caller its records are out while they
// sit in the host's batch processor — the aggregate nil means "nothing ran",
// not "the drain succeeded".
func TestFlush_ReportsNotOwnedBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_installPerSignalBackend(t,
		map[string]error{SignalLogs: nil, SignalTraces: nil, SignalMetrics: nil},
		SignalStatus{Logs: true, Traces: true, Metrics: true},
	)

	// Deliberately no Start(): the host's provider is installed, ours is not.
	rt := NewTelemetryRuntime(context.Background())

	result, err := rt.Flush(context.Background())
	if err != nil {
		t.Fatalf("flush: %v", err)
	}
	for name, sig := range map[string]SignalFlushResult{
		"logs":    result.Logs,
		"traces":  result.Traces,
		"metrics": result.Metrics,
	} {
		if !sig.NotOwned {
			t.Fatalf("expected %s NotOwned before setup, got %+v", name, sig)
		}
		if sig.Flushed {
			t.Fatalf("%s drained nothing and must not report Flushed: %+v", name, sig)
		}
	}
}

// The pre-setup path must not swallow NotInstalled: a signal with no provider
// at all is still NotInstalled, not NotOwned.
func TestFlush_NotInstalledStillWinsBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	_installPerSignalBackend(t,
		map[string]error{SignalLogs: nil},
		SignalStatus{Logs: true},
	)

	rt := NewTelemetryRuntime(context.Background())

	result, _ := rt.Flush(context.Background())
	if !result.Logs.NotOwned {
		t.Fatalf("expected logs NotOwned before setup, got %+v", result.Logs)
	}
	for name, sig := range map[string]SignalFlushResult{"traces": result.Traces, "metrics": result.Metrics} {
		if !sig.NotInstalled || sig.NotOwned {
			t.Fatalf("expected %s NotInstalled only, got %+v", name, sig)
		}
	}
}

// ProviderImmutableError.As answers only for the two error types it wraps.
// Returning true for anything else would make errors.As populate a target of
// an unrelated type with this error's fields.
func TestProviderImmutableError_AsRejectsAnUnrelatedTarget(t *testing.T) {
	err := NewProviderImmutableError("providers are installed")

	var schemaErr *EventSchemaError
	if err.As(&schemaErr) {
		t.Fatal("As must not claim an unrelated error type")
	}
	if schemaErr != nil {
		t.Fatalf("a rejected target must be left alone, got %+v", schemaErr)
	}

	// The two it does answer for still match.
	var cfgErr *ConfigurationError
	if !errors.As(error(err), &cfgErr) {
		t.Fatal("expected ConfigurationError to match")
	}
	var telErr *TelemetryError
	if !errors.As(error(err), &telErr) {
		t.Fatal("expected TelemetryError to match")
	}
}

// Before SetupTelemetry there is no live config to compare against, so no field
// can be provider-changing yet. The call still fails — nothing is set up — but
// it must fail for that reason and not be turned away as an attempt to change
// an installed provider, which would send a caller off to restart a process
// that had never started.
func TestUpdateConfig_DoesNotBlameProviderFieldsBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	rt := NewTelemetryRuntime(context.Background())
	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "renamed-before-setup"

	_, err := rt.UpdateConfig(context.Background(), cfg)
	if err == nil {
		t.Fatal("expected UpdateConfig to fail before setup")
	}
	var immutable *ProviderImmutableError
	if errors.As(err, &immutable) {
		t.Fatalf("provider-immutability must not be the complaint before setup: %v", err)
	}
}
