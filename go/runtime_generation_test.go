// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"sync"
	"testing"
)

// TestReconfigurePublishesNewGenerationWithoutMutatingOld pins the property the
// whole generation model exists for: a config a caller already holds must not
// change underneath them.
//
// Before generations, ReconfigureTelemetry called _applyHotFields(_runtimeCfg,
// target), which wrote every hot block straight through the currently published
// pointer. That pointer is not private — SetupTelemetry hands the same
// *TelemetryConfig to _configureLogger, so every live slog handler held it too.
func TestReconfigurePublishesNewGenerationWithoutMutatingOld(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "1.0")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	old := loadRuntimeGeneration()
	if old.config == nil {
		t.Fatal("expected a published generation after setup")
	}
	if old.config.Sampling.LogsRate != 1.0 {
		t.Fatalf("setup published LogsRate=%v, want 1.0", old.config.Sampling.LogsRate)
	}

	t.Setenv("PROVIDE_SAMPLING_LOGS_RATE", "0.25")
	if _, err := ReconfigureTelemetry(context.Background()); err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}

	current := loadRuntimeGeneration()
	if current.number == old.number {
		t.Errorf("reconfigure did not advance the generation number (both %d)", old.number)
	}
	if old.config.Sampling.LogsRate != 1.0 {
		t.Errorf("reconfigure mutated the previously published config: LogsRate=%v, want 1.0",
			old.config.Sampling.LogsRate)
	}
	if current.config.Sampling.LogsRate != 0.25 {
		t.Errorf("new generation has LogsRate=%v, want 0.25", current.config.Sampling.LogsRate)
	}
}

// TestGenerationNumberAdvancesOnEveryPublication covers the other two writers.
// UpdateRuntimeConfig and ReloadRuntimeFromEnv already cloned before swapping,
// but nothing observed that they published a *new* generation rather than
// quietly reusing the old one.
func TestGenerationNumberAdvancesOnEveryPublication(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	seen := map[uint64]bool{loadRuntimeGeneration().number: true}

	sampling := SamplingConfig{LogsRate: 0.5, TracesRate: 1.0, MetricsRate: 1.0}
	if err := UpdateRuntimeConfig(RuntimeOverrides{Sampling: &sampling}); err != nil {
		t.Fatalf("update failed: %v", err)
	}
	if n := loadRuntimeGeneration().number; seen[n] {
		t.Errorf("UpdateRuntimeConfig reused generation %d", n)
	} else {
		seen[n] = true
	}

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}
	if n := loadRuntimeGeneration().number; seen[n] {
		t.Errorf("ReloadRuntimeFromEnv reused generation %d", n)
	}
}

// TestGenerationSnapshotIsNotAliasedToTheLiveConfig checks that a caller cannot
// reach back into the published generation through the copy it was handed —
// including through the reference-typed fields, which a shallow copy would
// share.
func TestGenerationSnapshotIsNotAliasedToTheLiveConfig(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	t.Setenv("PROVIDE_LOG_MODULE_LEVELS", "probe=DEBUG")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	snapshot := loadRuntimeGeneration()
	if snapshot.config.Logging.ModuleLevels["probe"] != "DEBUG" {
		t.Fatalf("expected module level to be published, got %v", snapshot.config.Logging.ModuleLevels)
	}
	snapshot.config.Logging.Level = "vandalized"
	snapshot.config.Logging.ModuleLevels["probe"] = "vandalized"

	fresh := loadRuntimeGeneration()
	if fresh.config.Logging.Level == "vandalized" {
		t.Error("mutating a snapshot changed the published log level")
	}
	if fresh.config.Logging.ModuleLevels["probe"] == "vandalized" {
		t.Error("mutating a snapshot's ModuleLevels map changed the published one")
	}
}

// TestConcurrentLoggingAndReconfigureUsesWholeGenerations is the race-detector
// case. Emitting reads the config the handler was built with, while
// reconfiguration republishes; if the two share a *TelemetryConfig, -race
// reports a write to Logging/Sampling concurrent with the handler's read of
// Logging.Level and its range over Logging.ModuleLevels.
func TestConcurrentLoggingAndReconfigureUsesWholeGenerations(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	ctx := context.Background()
	levels := []string{"INFO", "DEBUG", "WARNING"}
	var wg sync.WaitGroup
	for i := range 60 {
		wg.Add(2)
		go func() {
			defer wg.Done()
			GetLogger(ctx, "race.probe").Info("event", "i", i)
		}()
		go func() {
			defer wg.Done()
			cfg := DefaultTelemetryConfig()
			cfg.Logging.Level = levels[i%len(levels)]
			cfg.Logging.ModuleLevels = map[string]string{"race": levels[i%len(levels)]}
			if _, err := ReconfigureTelemetry(ctx, WithConfig(cfg)); err != nil {
				t.Errorf("reconfigure failed: %v", err)
			}
		}()
	}
	wg.Wait()
}

// TestLoadRuntimeGenerationBeforeSetup covers the pre-setup and post-shutdown
// state: no generation has been published, so callers get the zero value rather
// than a nil dereference.
func TestLoadRuntimeGenerationBeforeSetup(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	empty := loadRuntimeGeneration()
	if empty.number != 0 || empty.config != nil || empty.logger != nil {
		t.Fatalf("expected the zero generation before setup, got %+v", empty)
	}
}

// TestLoggerTracksConfiguration covers the accessor that exists so
// concurrent code never has to read the exported Logger variable directly.
func TestLoggerTracksConfiguration(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	if Logger() != nil {
		t.Fatal("expected no default logger before setup")
	}

	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	first := Logger()
	if first == nil {
		t.Fatal("expected a default logger after setup")
	}

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Level = "DEBUG"
	if _, err := ReconfigureTelemetry(context.Background(), WithConfig(cfg)); err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}
	if second := Logger(); second == first {
		t.Error("expected reconfiguration to publish a rebuilt logger")
	}

	resetSetupState(t)
	if Logger() != nil {
		t.Error("expected the default logger to be cleared on teardown")
	}
}
