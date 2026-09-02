// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

//go:build windows

package telemetry

import (
	"context"
	"os"
	"strings"
	"syscall"
	"testing"
	"unicode/utf16"
	"unsafe"
)

// The console tests: a real console screen buffer, written through the whole
// SDK, read back cell by cell.
//
// Nothing else in this repository can look at one. Every other test writes into
// a bytes.Buffer, which holds whatever bytes it is handed — and CI cannot do it
// either, because GitHub Actions redirects every stream to a pipe, so no job has
// a console at all. Hence AllocConsole, which gives this process one whether the
// runner had it or not.
//
// The first thing these tests established was that a premise was wrong: the
// output code page does not affect Go's console output, because Go does not
// write bytes to a console. That is pinned below rather than merely believed.

var (
	_procAllocConsole              = _kernel32.NewProc("AllocConsole")
	_procReadConsoleOutputCharW    = _kernel32.NewProc("ReadConsoleOutputCharacterW")
	_procGetConsoleScreenBufferInf = _kernel32.NewProc("GetConsoleScreenBufferInfo")
	_procGetConsoleOutCP           = _kernel32.NewProc("GetConsoleOutputCP")
	_procSetConsoleOutCP           = _kernel32.NewProc("SetConsoleOutputCP")
)

const _codePage437 = uintptr(437)

// A non-ASCII character the console can actually store.
//
// Not an emoji, deliberately. A console screen buffer holds UTF-16 code units
// one per cell, so an astral character — every emoji — has no cell to live in
// and conhost stores U+FFFD instead. Windows Terminal renders one because its
// own buffer is not conhost's; asking the legacy buffer for it is asking the
// platform for something it does not do.
const _nonASCII = "checkmark ✓"

// consoleHandle attaches a console to this process and returns its screen
// buffer as a file.
//
// AllocConsole fails when the process already has one — a developer running the
// suite from a terminal — and that is not an error: CONOUT$ then opens the
// console that is already there.
func consoleHandle(t *testing.T) *os.File {
	t.Helper()
	_, _, _ = _procAllocConsole.Call()

	name, err := syscall.UTF16PtrFromString("CONOUT$")
	if err != nil {
		t.Fatalf("CONOUT$: %v", err)
	}
	handle, err := syscall.CreateFile(
		name,
		syscall.GENERIC_READ|syscall.GENERIC_WRITE,
		syscall.FILE_SHARE_READ|syscall.FILE_SHARE_WRITE,
		nil,
		syscall.OPEN_EXISTING,
		0,
		0,
	)
	if err != nil {
		t.Fatalf("opening CONOUT$ failed (%v); this environment has no console to test", err)
	}
	f := os.NewFile(uintptr(handle), "CONOUT$")
	t.Cleanup(func() { _ = f.Close() })
	return f
}

// consoleInfo is the head of CONSOLE_SCREEN_BUFFER_INFO: two COORDs of
// {X, Y int16}, the attributes, the window rect and the maximum window size.
type consoleInfo struct {
	size              [2]int16
	cursorPosition    [2]int16
	attributes        uint16
	window            [4]int16
	maximumWindowSize [2]int16
}

func consoleBufferInfo(t *testing.T, f *os.File) consoleInfo {
	t.Helper()
	var info consoleInfo
	if ret, _, err := _procGetConsoleScreenBufferInf.Call(
		uintptr(syscall.Handle(f.Fd())), uintptr(unsafe.Pointer(&info)),
	); ret == 0 {
		t.Fatalf("GetConsoleScreenBufferInfo: %v", err)
	}
	return info
}

// consoleCursor is where the next write will land, as the packed COORD the
// console API takes: X in the low word, Y in the high word.
//
// A process has one console, so every test here shares it, and reading from the
// top of the buffer finds whatever an earlier test left there. Reading from the
// cursor is what makes each assertion about its own write.
func consoleCursor(t *testing.T, f *os.File) uintptr {
	t.Helper()
	info := consoleBufferInfo(t, f)
	return uintptr(uint32(uint16(info.cursorPosition[1]))<<16 | uint32(uint16(info.cursorPosition[0])))
}

// consoleTextFrom reads the console screen buffer back as text, starting at the
// packed COORD start.
//
// The buffer is a grid of cells, so a wrapped line arrives with no separator and
// trailing cells arrive as spaces; the caller looks for a substring rather than
// parsing lines.
func consoleTextFrom(t *testing.T, f *os.File, start uintptr) string {
	t.Helper()
	info := consoleBufferInfo(t, f)

	// Two screens' worth of cells is plenty for one record and keeps the read
	// bounded on a buffer whose height is often 9001 lines.
	count := uint32(info.size[0]) * 50
	buf := make([]uint16, count)
	var read uint32
	if ret, _, err := _procReadConsoleOutputCharW.Call(
		uintptr(syscall.Handle(f.Fd())),
		uintptr(unsafe.Pointer(&buf[0])),
		uintptr(count),
		start,
		uintptr(unsafe.Pointer(&read)),
	); ret == 0 {
		t.Fatalf("ReadConsoleOutputCharacterW: %v", err)
	}
	return string(utf16.Decode(buf[:read]))
}

// onCodePage437 puts the console on a legacy code page for the test's duration.
func onCodePage437(t *testing.T) {
	t.Helper()
	original, _, _ := _procGetConsoleOutCP.Call()
	if ret, _, err := _procSetConsoleOutCP.Call(_codePage437); ret == 0 {
		t.Fatalf("SetConsoleOutputCP(437): %v", err)
	}
	t.Cleanup(func() { _, _, _ = _procSetConsoleOutCP.Call(original) })
}

// A record carrying non-ASCII reaches a Windows console intact, on the code page
// a console starts with.
//
// This is the assertion the whole file exists for, and it passes without this
// SDK touching the code page — which is the point. Go classifies a console
// handle as kindConsole and internal/poll's writeConsole decodes the UTF-8,
// encodes UTF-16 and calls WriteConsoleW, so what the console decodes with
// never enters the picture.
func TestWindowsConsole_NonASCIISurvivesADefaultCodePage(t *testing.T) {
	consoleReset(t)
	console := consoleHandle(t)
	onCodePage437(t)

	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", LogFormatJSON)
	if _, err := SetupTelemetry(WithLogOutput(console)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	start := consoleCursor(t, console)
	GetLogger(context.Background(), "console").Info("console.render.ok", "glyph", _nonASCII)

	if text := consoleTextFrom(t, console, start); !strings.Contains(text, _nonASCII) {
		t.Errorf("the console does not hold what was logged; it holds: %q", strings.TrimSpace(text))
	}
}

// The code page this SDK leaves alone is genuinely irrelevant to Go's output.
//
// Written straight to the handle with no SDK in the path, so what it pins is
// the runtime's behaviour rather than this package's. If a future Go release
// stopped routing console writes through WriteConsoleW, this fails and says so
// — which is the only warning there would be that the code page has become
// this SDK's problem after all, as it is C#'s.
func TestWindowsConsole_GoDoesNotWriteBytesToAConsole(t *testing.T) {
	consoleReset(t)
	console := consoleHandle(t)
	onCodePage437(t)

	start := consoleCursor(t, console)
	if _, err := console.Write([]byte("uncorrected " + _nonASCII + "\n")); err != nil {
		t.Fatalf("writing to the console: %v", err)
	}

	if text := consoleTextFrom(t, console, start); !strings.Contains(text, _nonASCII) {
		t.Errorf(
			"CP437 mangled Go's console output, so the code page now matters here; it holds: %q",
			strings.TrimSpace(text),
		)
	}
}

// Nothing this SDK does changes the console's code page.
//
// The host owns it. Changing it would be a process-wide side effect bought for
// nothing, given the write path above.
func TestWindowsConsole_TheCodePageIsLeftAlone(t *testing.T) {
	consoleReset(t)
	console := consoleHandle(t)
	onCodePage437(t)

	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	if _, err := SetupTelemetry(WithLogOutput(console)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if cp, _, _ := _procGetConsoleOutCP.Call(); cp != _codePage437 {
		t.Errorf("the console output code page is %d; the host set %d and nothing here should move it", cp, _codePage437)
	}
}

// Colour is reported from virtual-terminal processing, not from the handle
// being a character device.
//
// A Windows console handle carries os.ModeCharDevice, so the old probe said
// "colour is fine" on every console, legacy conhost included — where the
// escapes print literally. Preparation is what establishes the answer, so
// before it runs the answer is no.
func TestWindowsConsole_ColourFollowsVirtualTerminalProcessing(t *testing.T) {
	consoleReset(t)
	console := consoleHandle(t)

	if _terminalRendersANSI(console) {
		t.Error("an unprepared console was reported as rendering ANSI")
	}

	ansi, restore := _prepareConsole(console)
	if restore == nil {
		t.Fatal("_prepareConsole found no console to prepare")
	}
	t.Cleanup(restore)

	var mode uint32
	if err := syscall.GetConsoleMode(syscall.Handle(console.Fd()), &mode); err != nil {
		t.Fatalf("GetConsoleMode: %v", err)
	}
	vt := mode&_enableVirtualTerminal != 0
	if ansi != vt {
		t.Errorf("_prepareConsole reported ansi=%v while the console mode says vt=%v", ansi, vt)
	}
	if !vt {
		t.Skip("this console refuses ENABLE_VIRTUAL_TERMINAL_PROCESSING; the rest of the assertion needs it set")
	}

	_prepareLogConsole(console)
	if !_terminalRendersANSI(console) {
		t.Error("a prepared VT console was not reported as rendering ANSI")
	}
}

// Shutdown puts the console mode back the way the host had it.
func TestWindowsConsole_ShutdownRestoresTheConsoleMode(t *testing.T) {
	consoleReset(t)
	console := consoleHandle(t)

	var before uint32
	if err := syscall.GetConsoleMode(syscall.Handle(console.Fd()), &before); err != nil {
		t.Fatalf("GetConsoleMode: %v", err)
	}

	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	if _, err := SetupTelemetry(WithLogOutput(console)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	var after uint32
	if err := syscall.GetConsoleMode(syscall.Handle(console.Fd()), &after); err != nil {
		t.Fatalf("GetConsoleMode: %v", err)
	}
	if before != after {
		t.Errorf("console mode is %#x after shutdown, want the host's %#x", after, before)
	}
}
