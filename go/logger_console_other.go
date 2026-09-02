// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

//go:build !windows

package telemetry

import "os"

// _prepareConsole is a no-op away from Windows.
//
// A Unix terminal reads UTF-8 because the locale says so and renders ANSI
// without being asked, so there is nothing to set and nothing to restore. The
// returned restore is non-nil for a character device all the same: it is what
// tells the caller a console was found, and it is what makes the ANSI answer
// come from here on every platform rather than from a Windows-shaped special
// case in the terminal probe.
func _prepareConsole(f *os.File) (ansi bool, restore func()) {
	if !_isTerminalFile(f) {
		return false, nil
	}
	return true, func() {}
}

// _terminalRendersANSI reports whether f is a terminal that renders ANSI.
//
// Away from Windows the two questions are one: a character device is a
// terminal, and a terminal renders escapes. The answer does not depend on setup
// having run, which keeps a pretty logger built before SetupTelemetry coloured
// exactly as it always was.
func _terminalRendersANSI(f *os.File) bool {
	return _isTerminalFile(f)
}
