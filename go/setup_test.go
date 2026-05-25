// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"errors"
	"log/slog"
	"sync"
	"testing"
	"time"
)

// resetSetupState clears all setup state and related subsystems between tests.
// It also blanks OTel endpoint env vars so unit tests run isolated from any real
// OTLP exporters configured in the developer or CI environment — auto-wiring in
// _buildDefaultMeterProvider only fires when the endpoint is non-empty.
func resetSetupState(t *testing.T) {
	t.Helper()
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "")
	t.Setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "")
	t.Setenv("PROVIDE_LOG_LEVEL", "")
	_resetSetup()
	_resetSamplingPolicies()
	_resetQueuePolicy()
	_resetResiliencePolicies()
	_resetHealth()
}

func TestSetupTelemetryReturnsConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg.ServiceName == "" {
		t.Error("expected non-empty ServiceName")
	}
}

func TestSetupTelemetryIdempotent(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg1, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("first setup failed: %v", err)
	}

	cfg2, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("second setup failed: %v", err)
	}

	if cfg1.ServiceName != cfg2.ServiceName {
		t.Error("expected equivalent config values on second call (idempotent)")
	}
}

func TestShutdownTelemetryResetsState(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	prevDefault := slog.Default()

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	// After shutdown the config should be nil.
	cfg := GetRuntimeConfig()
	if cfg != nil {
		t.Error("expected nil config after shutdown")
	}
	if Logger != nil {
		t.Error("expected package logger to be nil after shutdown")
	}
	if slog.Default() != prevDefault {
		t.Error("expected slog default to be restored after shutdown")
	}
}

func TestShutdownThenSetupReinitialises(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "initial-service")

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("first setup failed: %v", err)
	}
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	t.Setenv("PROVIDE_TELEMETRY_SERVICE_NAME", "restarted-service")

	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("second setup failed: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil config after re-setup")
	}
	if cfg.ServiceName != "restarted-service" {
		t.Fatalf("expected re-setup to pick up fresh config, got %q", cfg.ServiceName)
	}
}

func TestShutdownTelemetryClearsLazyLoggerState(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	prevDefault := slog.Default()
	GetLogger(context.Background(), "lazy").Info("lazy.logger.before.setup")

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	if Logger != nil {
		t.Fatal("expected lazy logger state to be cleared by shutdown")
	}
	if slog.Default() != prevDefault {
		t.Fatal("expected slog default to be restored after lazy logger shutdown")
	}
}

func TestGetLoggerBeforeSetupAppliesEnvLogSamplingPolicy(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0")
	before := GetHealthSnapshot()
	GetLogger(context.Background(), "lazy.env.sampling").Info("lazy.logger.sampled.out")
	after := GetHealthSnapshot()

	if after.LogsEmitted != before.LogsEmitted {
		t.Fatalf("expected lazy env sampling=0 to drop log before emission: before=%d after=%d", before.LogsEmitted, after.LogsEmitted)
	}
	if after.LogsDropped <= before.LogsDropped {
		t.Fatalf("expected lazy env sampling=0 to increment dropped logs: before=%d after=%d", before.LogsDropped, after.LogsDropped)
	}
}

func TestSetupAppliesSamplingFromEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.5")

	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if cfg.Sampling.LogsRate != 0.5 {
		t.Errorf("expected LogsRate=0.5, got %v", cfg.Sampling.LogsRate)
	}

	policy, err := GetSamplingPolicy(signalLogs)
	if err != nil {
		t.Fatal(err)
	}
	if policy.DefaultRate != 0.5 {
		t.Errorf("expected sampling policy DefaultRate=0.5, got %v", policy.DefaultRate)
	}
}

func TestSetupAppliesBackpressureFromEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_BACKPRESSURE_LOGS_MAXSIZE", "42")

	cfg, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if cfg.Backpressure.LogsMaxSize != 42 {
		t.Errorf("expected LogsMaxSize=42, got %v", cfg.Backpressure.LogsMaxSize)
	}

	qp := GetQueuePolicy()
	if qp.LogsMaxSize != 42 {
		t.Errorf("expected queue policy LogsMaxSize=42, got %v", qp.LogsMaxSize)
	}
}

func TestSetupAppliesExporterPolicyFromEnv(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_EXPORTER_LOGS_RETRIES", "3")
	t.Setenv("PROVIDE_EXPORTER_LOGS_BACKOFF_SECONDS", "0.5")
	t.Setenv("PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS", "9")
	t.Setenv("PROVIDE_EXPORTER_LOGS_FAIL_OPEN", "false")

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	policy := GetExporterPolicy(signalLogs)
	if policy.Retries != 3 || policy.BackoffSeconds != 0.5 || policy.TimeoutSeconds != 9 || policy.FailOpen {
		t.Fatalf("expected exporter policy from env, got %+v", policy)
	}
}

func TestSetupTelemetryStrictEventNameFromEnvWithoutStrictSchema(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_TELEMETRY_STRICT_SCHEMA", "false")
	t.Setenv("PROVIDE_TELEMETRY_STRICT_EVENT_NAME", "true")

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Fatal("expected runtime config after setup")
	}
	if cfg.StrictSchema {
		t.Fatal("strict schema should remain false when only strict event name is enabled")
	}
	if !cfg.EventSchema.StrictEventName {
		t.Fatal("strict event name should be enabled in runtime config")
	}
	if !GetStrictSchema() {
		t.Fatal("effective strict schema should be enabled when strict event name is true")
	}

	if _, err := EventName("User", "Login", "Ok"); err == nil {
		t.Fatal("expected strict event-name validation to reject uppercase segments")
	}
}

func TestSetupConcurrentOnlyOneInitialises(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	const goroutines = 10
	var wg sync.WaitGroup
	wg.Add(goroutines)

	for i := 0; i < goroutines; i++ {
		go func() {
			defer wg.Done()
			cfg, err := SetupTelemetry()
			if err != nil {
				t.Errorf("unexpected error in goroutine: %v", err)
			}
			if cfg == nil {
				t.Error("expected non-nil config from goroutine")
			}
		}()
	}
	wg.Wait()

	// Verify setup completed by checking we have a config.
	cfg := GetRuntimeConfig()
	if cfg == nil {
		t.Error("expected non-nil config after concurrent setup")
	}
}

func TestResetSetupClearsState(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	_resetSetup()

	if GetRuntimeConfig() != nil {
		t.Error("expected nil config after _resetSetup")
	}
}

func TestShutdownNoOpWhenNotSetUp(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// Calling shutdown when nothing is set up should be a no-op without error.
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("expected nil error, got %v", err)
	}
}

func TestSetupTelemetryConfigFromEnvError(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// An invalid sampling rate causes ConfigFromEnv to return an error.
	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "invalid")

	cfg, err := SetupTelemetry()
	if err == nil {
		t.Fatal("expected error from SetupTelemetry with invalid env var")
	}
	if cfg != nil {
		t.Error("expected nil config on error")
	}
}

func TestSetupWithProviderOptions(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_fakeBackend{}
	RegisterBackend("fake", backend)
	t.Cleanup(func() { UnregisterBackend("fake") })

	sentinel := struct{ name string }{name: "test-provider"}
	cfg, err := SetupTelemetry(
		WithTracerProvider(sentinel),
		WithMeterProvider(sentinel),
		WithLoggerProvider(sentinel),
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
	if backend.lastSetupCfg == nil {
		t.Fatal("expected backend to observe setup config")
	}
}

func TestSetupTelemetryIdempotentReturnsCopy(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	cfg1, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("first setup failed: %v", err)
	}

	cfg2, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("second setup failed: %v", err)
	}

	// The idempotent path should return a clone, not the live pointer.
	if cfg1 == cfg2 {
		t.Error("expected different pointers from idempotent SetupTelemetry calls")
	}

	// Mutating the returned config should not affect internal state.
	cfg2.ServiceName = "mutated-via-setup-return"

	cfg3 := GetRuntimeConfig()
	if cfg3 == nil {
		t.Fatal("expected non-nil config")
	}
	if cfg3.ServiceName == "mutated-via-setup-return" {
		t.Fatal("mutating SetupTelemetry return value should not affect internal state")
	}
}

func TestSetupTelemetry_AllowBlockingInEventLoopRoundTrip(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_EXPORTER_LOGS_ALLOW_BLOCKING_EVENT_LOOP", "true")
	t.Setenv("PROVIDE_EXPORTER_TRACES_ALLOW_BLOCKING_EVENT_LOOP", "false")
	t.Setenv("PROVIDE_EXPORTER_METRICS_ALLOW_BLOCKING_EVENT_LOOP", "true")

	_, err := SetupTelemetry()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	logs := GetExporterPolicy(signalLogs)
	if !logs.AllowBlockingInEventLoop {
		t.Error("expected logs AllowBlockingInEventLoop=true")
	}

	traces := GetExporterPolicy(signalTraces)
	if traces.AllowBlockingInEventLoop {
		t.Error("expected traces AllowBlockingInEventLoop=false")
	}

	metrics := GetExporterPolicy(signalMetrics)
	if !metrics.AllowBlockingInEventLoop {
		t.Error("expected metrics AllowBlockingInEventLoop=true")
	}
}

func TestShutdownTelemetry_AppliesBoundedDeadlineWhenCtxHasNone(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "0.05")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	// Background context has no deadline; ShutdownTelemetry must add one
	// derived from PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS so a
	// slow OTLP backend cannot block shutdown indefinitely.
	start := time.Now()
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}
	elapsed := time.Since(start)
	if elapsed > 500*time.Millisecond {
		t.Errorf("shutdown took %v, expected fast return under bounded deadline", elapsed)
	}
}

func TestShutdownTelemetry_HonoursCallerDeadline(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// Caller supplies a context with a deadline — the library MUST NOT
	// overwrite it with its own. Tested via the internal helper to keep
	// the assertion deterministic (no real OTel I/O).
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	_setupMu.Lock()
	d := _shutdownDeadlineForLocked(ctx)
	_setupMu.Unlock()
	if d != 0 {
		t.Errorf("expected _shutdownDeadlineForLocked=0 when caller has deadline, got %v", d)
	}
}

func TestShutdownTelemetry_DisableBoundingWithZeroTimeout(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// LogsShutdownTimeoutSeconds=0 means "no bound from the library" —
	// callers can opt out and rely on the OTel SDK / their own ctx.
	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "0")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	_setupMu.Lock()
	d := _shutdownDeadlineForLocked(context.Background())
	_setupMu.Unlock()
	if d != 0 {
		t.Errorf("expected no bounding when LogsShutdownTimeoutSeconds=0, got %v", d)
	}
}

func TestShutdownTelemetry_DeadlineHelperReturnsZeroWhenNoRuntimeConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// After resetSetupState _runtimeCfg is nil — the helper must return 0
	// rather than crashing on a nil dereference.
	_setupMu.Lock()
	d := _shutdownDeadlineForLocked(context.Background())
	_setupMu.Unlock()
	if d != 0 {
		t.Errorf("expected 0 when _runtimeCfg is nil, got %v", d)
	}
}

// _deadlineExceededBackend synthesises context.DeadlineExceeded on shutdown
// to exercise the library-bound suppression path. Other Backend methods
// promote from the embedded _fakeBackend.
type _deadlineExceededBackend struct{ _fakeBackend }

func (b *_deadlineExceededBackend) Shutdown(context.Context) error {
	return context.DeadlineExceeded
}

// _genericErrorBackend returns a non-deadline error to prove the suppression
// is narrowly scoped to context.DeadlineExceeded.
type _genericErrorBackend struct{ _fakeBackend }

func (b *_genericErrorBackend) Shutdown(context.Context) error {
	return errors.New("backend shutdown failed")
}

func TestShutdownTelemetry_SuppressesDeadlineExceededFromLibraryBound(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// Library-bounded shutdown that abandons a still-pending flush must
	// return nil — matches the Python / TS / Rust contract that bounded
	// shutdown "returns cleanly even when records are dropped." Surface a
	// fake backend that synthesises context.DeadlineExceeded to prove the
	// suppression is wired without depending on real OTel timing.
	_, _ = RegisterBackend("deadline-test", &_deadlineExceededBackend{})
	t.Cleanup(func() { _, _ = UnregisterBackend("deadline-test") })

	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "0.05")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Errorf("library-bounded shutdown must swallow DeadlineExceeded, got %v", err)
	}
}

func TestShutdownTelemetry_SurfacesNonDeadlineErrorsFromBackend(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// A non-deadline backend error must still propagate — the suppression
	// is narrow (context.DeadlineExceeded only).
	_, _ = RegisterBackend("backend-error", &_genericErrorBackend{})
	t.Cleanup(func() { _, _ = UnregisterBackend("backend-error") })

	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "0.05")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	err := ShutdownTelemetry(context.Background())
	if err == nil {
		t.Error("expected non-deadline backend error to propagate")
	}
}

func TestShutdownTelemetry_SurfacesCallerDeadlineExceeded(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	// When the caller supplies the deadline (not the library), surface
	// DeadlineExceeded as an error — the caller explicitly asked for that
	// bound and presumably wants to know it fired.
	_, _ = RegisterBackend("caller-deadline", &_deadlineExceededBackend{})
	t.Cleanup(func() { _, _ = UnregisterBackend("caller-deadline") })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	err := ShutdownTelemetry(ctx)
	if err == nil {
		t.Error("caller-supplied deadline must surface DeadlineExceeded")
	}
}

func TestShutdownTelemetry_DeadlineHelperReadsConfiguredTimeout(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_EXPORTER_LOGS_SHUTDOWN_TIMEOUT_SECONDS", "2.5")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	_setupMu.Lock()
	d := _shutdownDeadlineForLocked(context.Background())
	_setupMu.Unlock()
	want := 2500 * time.Millisecond
	if d != want {
		t.Errorf("expected %v from 2.5s config, got %v", want, d)
	}
}
