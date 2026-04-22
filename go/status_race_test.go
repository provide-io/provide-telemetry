// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"sync"
	"testing"
)

func TestGetRuntimeStatus_NoRaceWithProviderMutation(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	RegisterBackend("fake", &_fakeBackend{})
	t.Cleanup(func() { UnregisterBackend("fake") })

	var wg sync.WaitGroup
	wg.Add(2)

	go func() {
		defer wg.Done()
		for i := 0; i < 200; i++ {
			_setupMu.Lock()
			_setupDone = true
			_runtimeCfg = DefaultTelemetryConfig()
			backend := _activeBackendLocked().(*_fakeBackend)
			backend.providers = SignalStatus{Logs: true, Traces: true, Metrics: true}
			_setupMu.Unlock()

			_setupMu.Lock()
			_setupDone = false
			_runtimeCfg = nil
			backend = _activeBackendLocked().(*_fakeBackend)
			backend.providers = SignalStatus{}
			_setupMu.Unlock()
		}
	}()

	go func() {
		defer wg.Done()
		for i := 0; i < 200; i++ {
			_ = GetRuntimeStatus()
		}
	}()

	wg.Wait()
}
