// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"io"
	"os"
	"sync"
)

// Console preparation: what this SDK does to the terminal it writes to.
//
// Only Windows needs anything. Go's os.Stderr is an ordinary handle and writes
// go out through WriteFile, so the bytes are interpreted by the console's
// *output code page* — CP437 or CP1252 on a default console, not UTF-8. Every
// non-ASCII byte this SDK writes then renders as mojibake, which is what a host
// prefixing its log lines with an emoji sees. The runtimes behind the other
// SDKs (CPython's _WindowsConsoleIO, libuv's uv_tty_write, Rust's std stdio)
// convert to UTF-16 and call WriteConsoleW, so the code page never reaches
// them; Go and C# are the two that write bytes.
//
// ANSI is the same shape of problem. A Windows console handle carries
// os.ModeCharDevice, so the terminal probe says "colour is fine here" — but a
// console renders ANSI only once ENABLE_VIRTUAL_TERMINAL_PROCESSING is set on
// it. Windows Terminal and current conhost set it themselves; legacy conhost
// does not, and prints the escapes literally. The platform least likely to
// render ANSI was the one where colour was switched on unasked.
//
// So preparation is: make the console UTF-8, enable VT, and report colour
// capability from whether VT actually took. Both changes are restored at
// shutdown, and neither is made when the destination is not a console — a
// file, a pipe, or a writer the host supplied gets exactly the bytes it would
// have got before.

// _consoleGuard owns the process's single console preparation.
//
// A mutex rather than an atomic because prepare and restore are pairs: a setup
// racing a shutdown must not leave the console holding settings whose restore
// has already run.
var _consoleGuard = _consolePrep{} //nolint:gochecknoglobals

type _consolePrep struct {
	mu      sync.Mutex
	restore func()
	ansi    bool
}

// _prepareLogConsole readies w's console, if w is one, for what this SDK
// writes. Idempotent: a second call with a preparation already in place is a
// no-op, so the reconfigure paths that rebuild the logger chain neither redo it
// nor lose the restore captured the first time.
func _prepareLogConsole(w io.Writer) {
	_consoleGuard.mu.Lock()
	defer _consoleGuard.mu.Unlock()
	if _consoleGuard.restore != nil {
		return
	}
	// Assigned together, with no guard between them: _prepareConsole reports
	// "no console here" as a nil restore, and storing that leaves the guard in
	// the unprepared state it was already in, so a later setup with a console
	// destination still gets its chance.
	_consoleGuard.ansi, _consoleGuard.restore = _prepareConsole(_consoleFile(w))
}

// _restoreLogConsole puts back whatever _prepareLogConsole changed.
func _restoreLogConsole() {
	_consoleGuard.mu.Lock()
	defer _consoleGuard.mu.Unlock()
	if _consoleGuard.restore == nil {
		return
	}
	_consoleGuard.restore()
	_consoleGuard.restore = nil
	_consoleGuard.ansi = false
}

// _consoleANSIEnabled reports whether the prepared console renders ANSI.
func _consoleANSIEnabled() bool {
	_consoleGuard.mu.Lock()
	defer _consoleGuard.mu.Unlock()
	return _consoleGuard.ansi
}

// _consoleFile extracts the *os.File a destination writes to, or nil.
//
// A host that hands over a writer of its own is not a console as far as this
// SDK is concerned even if it eventually reaches one: it owns that path, and
// changing a console it merely borrows would be reaching past the seam it used
// to take ownership.
func _consoleFile(w io.Writer) *os.File {
	f, _ := w.(*os.File)
	return f
}
