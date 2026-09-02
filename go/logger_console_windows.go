// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

//go:build windows

package telemetry

import (
	"os"
	"syscall"
)

// ENABLE_VIRTUAL_TERMINAL_PROCESSING.
const _enableVirtualTerminal = uint32(0x0004)

// The one console call the stdlib does not wrap. syscall exports
// GetConsoleMode and not its setter, and reaching for
// golang.org/x/sys/windows would be this package's first third-party
// dependency — for a call whose arguments are both plain integers, so no
// unsafe.Pointer is involved either.
//
//nolint:gochecknoglobals // lazy DLL handles are the documented syscall idiom
var (
	_kernel32           = syscall.NewLazyDLL("kernel32.dll")
	_procSetConsoleMode = _kernel32.NewProc("SetConsoleMode")
)

// _prepareConsole makes a Windows console able to render what this SDK writes.
//
// Only ANSI needs anything. A console renders escape sequences only once
// ENABLE_VIRTUAL_TERMINAL_PROCESSING is set on it; Windows Terminal and current
// conhost set it themselves, legacy conhost does not and prints "ESC[36m"
// literally. Whether enabling it succeeded is the answer to "does ANSI work
// here", which is why colour is reported from this result rather than from the
// handle being a character device — every console is one.
//
// The output code page is deliberately *not* touched. It decides how a console
// decodes the bytes written to it, but Go never writes bytes to one: os.File
// classifies a console handle as kindConsole and internal/poll's writeConsole
// decodes the UTF-8, encodes UTF-16 and calls WriteConsoleW, so the code page
// is not in the path at all. Setting it would change the host's console to no
// purpose. C# is the SDK that needs it, because .NET encodes through
// Console.OutputEncoding and writes the resulting bytes.
//
// A handle that is not a console fails GetConsoleMode, and this returns a nil
// restore — the signal that nothing was found and nothing was touched. A
// console that already has the mode bit keeps it, and is not restored to
// something it never had.
func _prepareConsole(f *os.File) (ansi bool, restore func()) {
	if f == nil {
		return false, nil
	}
	handle := syscall.Handle(f.Fd())

	var mode uint32
	if err := syscall.GetConsoleMode(handle, &mode); err != nil {
		// A file, a pipe, or a redirected stream. Nothing here applies, and its
		// bytes were already correct UTF-8.
		return false, nil
	}
	if mode&_enableVirtualTerminal != 0 {
		return true, func() {}
	}
	if ret, _, _ := _procSetConsoleMode.Call(uintptr(handle), uintptr(mode|_enableVirtualTerminal)); ret == 0 {
		// A console that refuses VT is a console all the same, so a restore is
		// returned: it is what tells the caller one was found.
		return false, func() {}
	}
	previous := uintptr(mode)
	return true, func() { _, _, _ = _procSetConsoleMode.Call(uintptr(handle), previous) }
}

// _terminalRendersANSI reports whether f is a console that renders ANSI.
//
// A Windows console handle carries os.ModeCharDevice, so the character-device
// test alone says yes on every console — including a legacy conhost, which
// prints "\x1b[36m" literally. The real answer is whether
// ENABLE_VIRTUAL_TERMINAL_PROCESSING is on, which _prepareConsole established
// when logging was configured. Before that, or when enabling it failed, colour
// is off: the platform least able to render ANSI should not be the one that
// emits it unasked.
func _terminalRendersANSI(f *os.File) bool {
	return _isTerminalFile(f) && _consoleANSIEnabled()
}
