// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"strings"
	"testing"
)

// setupWithLogBridge installs a backend whose log bridge records everything it
// receives, and returns it. An OTLP logs endpoint is what makes the backend
// report a live logs provider.
func setupWithLogBridge(t *testing.T) *_fakeBackend {
	t.Helper()
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_fakeBackend{}
	RegisterBackend("fake", backend)
	t.Cleanup(func() { UnregisterBackend("fake") })

	// Configured through the environment, not WithConfig: a reload reads the
	// environment, and a reload whose config disagrees with the live one is
	// refused as a provider change before it ever reaches the logger.
	t.Setenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "http://localhost:4318")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if !backend.providers.Logs {
		t.Fatal("backend reports no logs provider; the bridge would never be wired")
	}
	return backend
}

// bridgeSaw reports whether the bridge received a record carrying msg.
func bridgeSaw(backend *_fakeBackend, msg string) bool {
	for _, body := range backend.logBody {
		if strings.Contains(body, msg) {
			return true
		}
	}
	return false
}

// The package logger keeps exporting after a reconfigure.
//
// Every reload path rebuilds the handler chain through _configureLogger, which
// is a different construction from the one that installed the bridge. A logger
// that silently stops exporting while the config still reports OTLPEnabled is
// worse than one that fails: nothing observable changes.
func TestLogger_BridgeSurvivesReconfigureTelemetry(t *testing.T) {
	backend := setupWithLogBridge(t)

	Logger().Info("before.reconfigure.ok")
	if !bridgeSaw(backend, "before.reconfigure.ok") {
		t.Fatal("bridge never received the pre-reconfigure record; the test is not wired")
	}

	if _, err := ReconfigureTelemetry(context.Background()); err != nil {
		t.Fatalf("reconfigure failed: %v", err)
	}

	Logger().Info("after.reconfigure.ok")
	if !bridgeSaw(backend, "after.reconfigure.ok") {
		t.Errorf("bridge stopped receiving after reconfigure; it holds %v", backend.logBody)
	}
}

func TestLogger_BridgeSurvivesUpdateRuntimeConfig(t *testing.T) {
	backend := setupWithLogBridge(t)

	logging := GetRuntimeConfig().Logging
	logging.Level = LogLevelDebug
	if err := UpdateRuntimeConfig(RuntimeOverrides{Logging: &logging}); err != nil {
		t.Fatalf("update failed: %v", err)
	}

	Logger().Info("after.update.ok")
	if !bridgeSaw(backend, "after.update.ok") {
		t.Errorf("bridge stopped receiving after update; it holds %v", backend.logBody)
	}
}

func TestLogger_BridgeSurvivesReloadRuntimeFromEnv(t *testing.T) {
	backend := setupWithLogBridge(t)

	if err := ReloadRuntimeFromEnv(); err != nil {
		t.Fatalf("reload failed: %v", err)
	}

	Logger().Info("after.reload.ok")
	if !bridgeSaw(backend, "after.reload.ok") {
		t.Errorf("bridge stopped receiving after reload; it holds %v", backend.logBody)
	}
}
