// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// consoleReset returns the package's console state to "nothing prepared" so one
// test's preparation cannot decide the next one's colour.
func consoleReset(t *testing.T) {
	t.Helper()
	_restoreLogConsole()
	t.Cleanup(_restoreLogConsole)
}

// A writer that is not an *os.File is never a console, whatever it wraps.
//
// A host that hands over its own writer owns the path to the terminal; changing
// a console it merely borrows would be reaching past the seam it used to take
// ownership.
func TestConsole_AWrappedWriterIsNotAConsole(t *testing.T) {
	consoleReset(t)
	if _consoleFile(&bytes.Buffer{}) != nil {
		t.Error("a bytes.Buffer was taken for a console")
	}
	_prepareLogConsole(&bytes.Buffer{})
	if _consoleANSIEnabled() {
		t.Error("preparing a buffer reported an ANSI-capable console")
	}
}

// An *os.File that is a regular file is not a console either.
func TestConsole_ARegularFileIsNotAConsole(t *testing.T) {
	consoleReset(t)
	path := filepath.Join(t.TempDir(), "log.txt")
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	t.Cleanup(func() { _ = f.Close() })

	if _consoleFile(f) != f {
		t.Error("an *os.File was not recognised as one")
	}
	_prepareLogConsole(f)
	if _consoleANSIEnabled() {
		t.Error("a regular file reported an ANSI-capable console")
	}
	if _terminalRendersANSI(f) {
		t.Error("a regular file was reported as rendering ANSI")
	}
}

// Preparation happens once. Every reconfigure path rebuilds the logger chain,
// and a second preparation would either redo the work or — worse — overwrite
// the restore captured the first time with one that puts back the settings this
// SDK had already installed.
func TestConsole_PreparationIsIdempotent(t *testing.T) {
	consoleReset(t)
	var prepared int
	restore := func() { prepared-- }

	_consoleGuard.mu.Lock()
	_consoleGuard.restore = restore
	_consoleGuard.ansi = true
	prepared++
	_consoleGuard.mu.Unlock()

	_prepareLogConsole(os.Stderr)
	if !_consoleANSIEnabled() {
		t.Error("a second preparation replaced the first one's state")
	}

	_restoreLogConsole()
	if prepared != 0 {
		t.Errorf("restore ran %d times, want exactly 1", 1-prepared)
	}
	if _consoleANSIEnabled() {
		t.Error("ANSI still reported after restore")
	}
}

// Restoring twice is safe: ShutdownTelemetry and _resetSetup both call it, and
// a test that shuts down and then resets must not put the console back twice.
func TestConsole_RestoreIsSafeToRepeat(t *testing.T) {
	consoleReset(t)
	calls := 0

	_consoleGuard.mu.Lock()
	_consoleGuard.restore = func() { calls++ }
	_consoleGuard.mu.Unlock()

	_restoreLogConsole()
	_restoreLogConsole()
	if calls != 1 {
		t.Errorf("restore ran %d times, want 1", calls)
	}
}

// A preparation that found no console leaves nothing to restore.
func TestConsole_NothingFoundLeavesNothingToRestore(t *testing.T) {
	consoleReset(t)
	path := filepath.Join(t.TempDir(), "log.txt")
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	t.Cleanup(func() { _ = f.Close() })

	if ansi, restore := _prepareConsole(f); ansi || restore != nil {
		t.Errorf("_prepareConsole on a regular file returned ansi=%v restore!=nil=%v", ansi, restore != nil)
	}
	if ansi, restore := _prepareConsole(nil); ansi || restore != nil {
		t.Errorf("_prepareConsole(nil) returned ansi=%v restore!=nil=%v", ansi, restore != nil)
	}
}
