// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

//go:build !windows

package telemetry

import (
	"os"
	"testing"
)

// charDevice opens a character device to stand in for a terminal.
//
// /dev/null is one, and it is the only one a test can rely on: CI has no
// controlling terminal, so /dev/tty is absent, and the stdlib has no pty. What
// is being tested is the mode bit the probe reads, which /dev/null carries
// exactly as a terminal does.
func charDevice(t *testing.T) *os.File {
	t.Helper()
	f, err := os.OpenFile(os.DevNull, os.O_WRONLY, 0)
	if err != nil {
		t.Fatalf("opening %s: %v", os.DevNull, err)
	}
	t.Cleanup(func() { _ = f.Close() })
	return f
}

// Away from Windows a character device needs no preparation, and reports both
// that one was found — a non-nil restore — and that it renders ANSI.
func TestConsole_CharacterDeviceNeedsNoPreparation(t *testing.T) {
	consoleReset(t)
	device := charDevice(t)

	ansi, restore := _prepareConsole(device)
	if !ansi {
		t.Error("a character device was reported as not rendering ANSI")
	}
	if restore == nil {
		t.Fatal("a character device produced no restore, so nothing was found")
	}
	restore()
}

// The ANSI answer here does not wait for setup: a pretty logger built before
// SetupTelemetry is coloured exactly as it always was.
func TestConsole_ANSIDoesNotDependOnPreparation(t *testing.T) {
	consoleReset(t)
	device := charDevice(t)

	if !_terminalRendersANSI(device) {
		t.Error("an unprepared character device was reported as not rendering ANSI")
	}
	if _consoleANSIEnabled() {
		t.Error("nothing was prepared, yet the guard reports a prepared console")
	}
}

// Preparing a character device records the restore, so shutdown has something
// to call even where the restore itself does nothing.
func TestConsole_PreparingACharacterDeviceRecordsARestore(t *testing.T) {
	consoleReset(t)
	_prepareLogConsole(charDevice(t))
	if !_consoleANSIEnabled() {
		t.Error("a prepared character device was not recorded as ANSI-capable")
	}
	_restoreLogConsole()
	if _consoleANSIEnabled() {
		t.Error("ANSI still reported after restore")
	}
}
