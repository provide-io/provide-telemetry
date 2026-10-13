// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"log/slog"
	"testing"
)

// A failed setup must leave every piece of process-wide state it touched
// exactly as it found it. Each value below is set to something neither the
// defaults nor the rejected config would produce, so a leak in any one of them
// shows up as a changed value.
func TestSetupTelemetryFailureRestoresPriorProcessState(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() {
		resetSetupState(t)
		ResetConsentForTests()
		SetStrictSchema(false)
	})
	t.Setenv(_consentEnvVar, "MINIMAL")

	_, _ = SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.3})
	_, _ = SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: 0.4})
	SetQueuePolicy(QueuePolicy{LogsMaxSize: 7, TracesMaxSize: 8, MetricsMaxSize: 9})
	ticket := TryAcquire(signalLogs)
	if ticket == nil {
		t.Fatal("expected a logs ticket under the prior queue policy")
	}
	priorExporter := ExporterPolicy{Retries: 2, BackoffSeconds: 0.5, TimeoutSeconds: 3, FailOpen: false}
	SetExporterPolicy(signalLogs, priorExporter)
	SetStrictSchema(true)
	SetConsentLevel(ConsentFunctional)
	priorLogger := slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil))
	SetLogger(priorLogger)
	priorDefault := slog.Default()
	var priorSink bytes.Buffer
	_installLogSink(&priorSink)
	priorSinkPtr := _activeLogSink.Load()

	cfg := DefaultTelemetryConfig()
	cfg.Sampling.LogsRate = 0.9
	cfg.Backpressure.LogsMaxSize = 99
	cfg.Exporter.LogsRetries = 5
	cfg.StrictSchema = false
	var candidateSink bytes.Buffer
	// No backend is registered, so a provider option fails wiring after the
	// policies, consent, logger and sink have all been applied.
	_, err := SetupTelemetry(WithConfig(cfg), WithLogOutput(&candidateSink), WithTracerProvider(struct{}{}))
	if err == nil {
		t.Fatal("expected provider options without a backend to fail setup")
	}

	if got, _ := GetSamplingPolicy(signalLogs); got.DefaultRate != 0.3 {
		t.Fatalf("logs sampling leaked: %v", got.DefaultRate)
	}
	if got, _ := GetSamplingPolicy(signalTraces); got.DefaultRate != 0.4 {
		t.Fatalf("traces sampling leaked: %v", got.DefaultRate)
	}
	if got := GetQueuePolicy(); got != (QueuePolicy{LogsMaxSize: 7, TracesMaxSize: 8, MetricsMaxSize: 9}) {
		t.Fatalf("queue policy leaked: %+v", got)
	}
	if got := GetExporterPolicy(signalLogs); got != priorExporter {
		t.Fatalf("exporter policy leaked: %+v", got)
	}
	if !GetStrictSchema() {
		t.Fatal("strict schema leaked")
	}
	if got := GetConsentLevel(); got != ConsentFunctional {
		t.Fatalf("consent from env leaked: %v", got)
	}
	if Logger() != priorLogger {
		t.Fatal("package logger leaked")
	}
	if slog.Default() != priorDefault {
		t.Fatal("slog default leaked")
	}
	if _activeLogSink.Load() != priorSinkPtr {
		t.Fatal("log sink leaked")
	}
	if _preTelemetryLogger != nil {
		t.Fatal("pre-telemetry logger leaked")
	}
	if GetRuntimeConfig() != nil || _runtimeSetupDone() {
		t.Fatal("failed setup left the runtime marked as set up")
	}

	// The ticket taken before setup still releases into the queue it came
	// from: the channel itself was restored, not a fresh one of the same size.
	Release(ticket)
	for range 7 {
		if TryAcquire(signalLogs) == nil {
			t.Fatal("restored logs queue lost capacity")
		}
	}
	if TryAcquire(signalLogs) != nil {
		t.Fatal("restored logs queue gained capacity")
	}
}

func TestSetupTelemetryFailureRestoresUnsetLoggerAndConsole(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	priorDefault := slog.Default()
	if _, err := SetupTelemetry(WithTracerProvider(struct{}{})); err == nil {
		t.Fatal("expected provider options without a backend to fail setup")
	}
	if Logger() != nil {
		t.Fatal("failed setup left a package logger installed")
	}
	if slog.Default() != priorDefault {
		t.Fatal("failed setup left its logger as the slog default")
	}
	if _activeLogSink.Load() != nil {
		t.Fatal("failed setup left a log sink installed")
	}

	// A successful setup afterwards still captures the real pre-telemetry
	// default, so shutdown hands slog back what the host had.
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup after rollback failed: %v", err)
	}
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown: %v", err)
	}
	if slog.Default() != priorDefault {
		t.Fatal("shutdown after a rolled-back setup did not restore the host's slog default")
	}
}

func TestSetupTelemetryFailureKeepsEarlierConsolePreparation(t *testing.T) {
	resetSetupState(t)
	restored := 0
	_consoleGuard.mu.Lock()
	_consoleGuard.restore = func() { restored++ }
	_consoleGuard.mu.Unlock()
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(WithTracerProvider(struct{}{})); err == nil {
		t.Fatal("expected provider options without a backend to fail setup")
	}
	if restored != 0 {
		t.Fatalf("rollback undid a console preparation it did not make (%d restores)", restored)
	}
	_restoreLogConsole()
	if restored != 1 {
		t.Fatalf("earlier console preparation was lost: %d restores", restored)
	}
}

func TestSetupTelemetryFailureUndoesItsOwnConsolePreparation(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	snap := _captureProcessState()
	restored := 0
	_consoleGuard.mu.Lock()
	_consoleGuard.restore = func() { restored++ }
	_consoleGuard.mu.Unlock()
	snap._restoreProcessState()
	if restored != 1 {
		t.Fatalf("rollback kept a console preparation made after capture: %d restores", restored)
	}
}
