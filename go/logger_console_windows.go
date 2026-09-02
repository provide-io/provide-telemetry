// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

//go:build windows

package telemetry

import (
	"os"
	"syscall"
)

// ENABLE_VIRTUAL_TERMINAL_PROCESSING and CP_UTF8.
const (
	_enableVirtualTerminal = uint32(0x0004)
	_codePageUTF8          = uintptr(65001)
)

// The three console calls the stdlib does not wrap. syscall exports
// GetConsoleMode and nothing else of this family, and reaching for
// golang.org/x/sys/windows would be this package's first third-party
// dependency — for three calls whose arguments are all plain integers, so no
// unsafe.Pointer is involved either.
//
//nolint:gochecknoglobals // lazy DLL handles are the documented syscall idiom
var (
	_kernel32            = syscall.NewLazyDLL("kernel32.dll")
	_procSetConsoleMode  = _kernel32.NewProc("SetConsoleMode")
	_procGetConsoleOutCP = _kernel32.NewProc("GetConsoleOutputCP")
	_procSetConsoleOutCP = _kernel32.NewProc("SetConsoleOutputCP")
)

// _prepareConsole makes a Windows console able to render what this SDK writes.
//
// Two changes, each made only when it is needed and each undone by the returned
// restore:
//
//   - The output code page becomes UTF-8. Go writes bytes straight to a console
//     handle, so without this every non-ASCII byte is decoded as CP437 or
//     CP1252 and rendered as mojibake.
//   - ENABLE_VIRTUAL_TERMINAL_PROCESSING is set, and whether that succeeded is
//     the answer to "does ANSI work here". Legacy conhost refuses it and prints
//     the escapes literally, which is why colour is reported from this result
//     rather than from the handle being a character device.
//
// A handle that is not a console fails GetConsoleMode, and this returns a nil
// restore — the signal that nothing was found and nothing was touched. A
// console that already holds either setting is left holding it, and is not
// restored to something it never had.
func _prepareConsole(f *os.File) (ansi bool, restore func()) {
	if f == nil {
		return false, nil
	}
	handle := syscall.Handle(f.Fd())

	var mode uint32
	if err := syscall.GetConsoleMode(handle, &mode); err != nil {
		// A file, a pipe, or a redirected stream. Its bytes are already correct
		// UTF-8 and none of this applies.
		return false, nil
	}

	undo := make([]func(), 0, 2)
	ansi = mode&_enableVirtualTerminal != 0
	if !ansi {
		if ret, _, _ := _procSetConsoleMode.Call(uintptr(handle), uintptr(mode|_enableVirtualTerminal)); ret != 0 {
			ansi = true
			previous := uintptr(mode)
			undo = append(undo, func() { _, _, _ = _procSetConsoleMode.Call(uintptr(handle), previous) })
		}
	}

	if previous, _, _ := _procGetConsoleOutCP.Call(); previous != _codePageUTF8 {
		if ret, _, _ := _procSetConsoleOutCP.Call(_codePageUTF8); ret != 0 {
			undo = append(undo, func() { _, _, _ = _procSetConsoleOutCP.Call(previous) })
		}
	}

	return ansi, func() {
		for _, step := range undo {
			step()
		}
	}
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
