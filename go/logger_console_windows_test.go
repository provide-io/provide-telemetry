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

// The console test: a real console screen buffer, written through the whole
// SDK, read back cell by cell.
//
// Nothing else in this repository can catch the bug it covers. Every other test
// writes into a bytes.Buffer, which holds whatever bytes it is handed — but the
// defect is that a console *decodes* those bytes with its output code page, so
// a buffer proves only that the SDK produced correct UTF-8, which was never in
// doubt. CI cannot catch it either: GitHub Actions redirects every stream to a
// pipe, so no job has a console at all. Hence AllocConsole, which gives this
// process one whether the runner had it or not.

var (
	_procAllocConsole              = _kernel32.NewProc("AllocConsole")
	_procReadConsoleOutputCharW    = _kernel32.NewProc("ReadConsoleOutputCharacterW")
	_procGetConsoleScreenBufferInf = _kernel32.NewProc("GetConsoleScreenBufferInfo")
)

const _codePage437 = uintptr(437)

// A non-ASCII character the console can actually store.
//
// Not an emoji, deliberately. A console screen buffer holds UTF-16 code units
// one per cell, so an astral character — every emoji — has no cell to live in
// and conhost stores U+FFFD instead, whatever the code page says. Windows
// Terminal renders one because its own buffer is not conhost's; the SDK cannot
// make the legacy one hold it, and a test asserting otherwise would be asking
// the platform for something it does not do.
//
// The code page is what this SDK controls, and it is what turns a stream of
// UTF-8 bytes from four mojibake characters into one correct one. That holds
// for every non-ASCII character, emoji included: the difference for an emoji is
// U+FFFD instead of the glyph on legacy conhost, and the glyph itself anywhere
// with a modern buffer.
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

// consoleText reads the console screen buffer back as text.
//
// The buffer is a grid of cells, so a wrapped line arrives with no separator
// and trailing cells arrive as spaces; the caller looks for a substring rather
// than parsing lines.
func consoleText(t *testing.T, f *os.File) string {
	t.Helper()
	// CONSOLE_SCREEN_BUFFER_INFO begins with COORD dwSize {X, Y int16}.
	var info struct {
		size              [2]int16
		cursorPosition    [2]int16
		attributes        uint16
		window            [4]int16
		maximumWindowSize [2]int16
	}
	handle := syscall.Handle(f.Fd())
	if ret, _, err := _procGetConsoleScreenBufferInf.Call(
		uintptr(handle), uintptr(unsafe.Pointer(&info)),
	); ret == 0 {
		t.Fatalf("GetConsoleScreenBufferInfo: %v", err)
	}

	// Two screens' worth of cells is plenty for one record and keeps the read
	// bounded on a buffer whose height is often 9001 lines.
	count := uint32(info.size[0]) * 50
	buf := make([]uint16, count)
	var read uint32
	if ret, _, err := _procReadConsoleOutputCharW.Call(
		uintptr(handle),
		uintptr(unsafe.Pointer(&buf[0])),
		uintptr(count),
		0, // COORD{0, 0}, packed as Y<<16|X
		uintptr(unsafe.Pointer(&read)),
	); ret == 0 {
		t.Fatalf("ReadConsoleOutputCharacterW: %v", err)
	}
	return string(utf16.Decode(buf[:read]))
}

// A non-ASCII record reaches a Windows console intact, whatever code page the
// console started on.
//
// This is the reported failure, from the outside: a host prefixes its log lines
// with an emoji to tell two runtimes apart in one stream, and on Windows every
// such line arrives as mojibake. Go writes bytes straight to the console handle,
// so a console left on CP437 or CP1252 decodes each UTF-8 byte separately.
func TestWindowsConsole_NonASCIISurvivesADefaultCodePage(t *testing.T) {
	consoleReset(t)
	console := consoleHandle(t)

	// Start from a legacy code page, so a pass proves this SDK set the console
	// rather than inheriting a friendly default from the runner.
	original, _, _ := _procGetConsoleOutCP.Call()
	if ret, _, err := _procSetConsoleOutCP.Call(_codePage437); ret == 0 {
		t.Fatalf("SetConsoleOutputCP(437): %v", err)
	}
	t.Cleanup(func() { _, _, _ = _procSetConsoleOutCP.Call(original) })

	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", LogFormatJSON)
	if _, err := SetupTelemetry(WithLogOutput(console)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	if cp, _, _ := _procGetConsoleOutCP.Call(); cp != _codePageUTF8 {
		t.Fatalf("console output code page is %d after setup, want %d", cp, _codePageUTF8)
	}

	GetLogger(context.Background(), "console").Info("console.render.ok", "glyph", _nonASCII)

	if text := consoleText(t, console); !strings.Contains(text, _nonASCII) {
		t.Errorf("the console does not hold what was logged; it holds: %q", strings.TrimSpace(text))
	}
}

// The same bytes on the code page a console starts with come out wrong.
//
// Without this the test above would pass on any runner whose console happened
// to be UTF-8 already, and would stop being about the defect. Writing straight
// to the handle, with no SDK in the path, is what isolates the code page as the
// cause.
func TestWindowsConsole_TheDefaultCodePageIsWhatBreaksIt(t *testing.T) {
	consoleReset(t)
	console := consoleHandle(t)

	original, _, _ := _procGetConsoleOutCP.Call()
	if ret, _, err := _procSetConsoleOutCP.Call(_codePage437); ret == 0 {
		t.Fatalf("SetConsoleOutputCP(437): %v", err)
	}
	t.Cleanup(func() { _, _, _ = _procSetConsoleOutCP.Call(original) })

	if _, err := console.Write([]byte("uncorrected " + _nonASCII + "\n")); err != nil {
		t.Fatalf("writing to the console: %v", err)
	}

	if text := consoleText(t, console); strings.Contains(text, _nonASCII) {
		t.Error("CP437 rendered UTF-8 correctly, so this test can no longer tell the fix from its absence")
	}
}

// Shutdown puts the console back the way the host had it.
func TestWindowsConsole_ShutdownRestoresTheCodePage(t *testing.T) {
	consoleReset(t)
	console := consoleHandle(t)

	original, _, _ := _procGetConsoleOutCP.Call()
	if ret, _, err := _procSetConsoleOutCP.Call(_codePage437); ret == 0 {
		t.Fatalf("SetConsoleOutputCP(437): %v", err)
	}
	t.Cleanup(func() { _, _, _ = _procSetConsoleOutCP.Call(original) })

	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	if _, err := SetupTelemetry(WithLogOutput(console)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	if cp, _, _ := _procGetConsoleOutCP.Call(); cp != _codePage437 {
		t.Errorf("console output code page is %d after shutdown, want the host's %d", cp, _codePage437)
	}
}

// A console the host already put on UTF-8 is left alone, and restoring does not
// set it to something it never had.
func TestWindowsConsole_AnAlreadyUTF8ConsoleIsLeftAlone(t *testing.T) {
	consoleReset(t)
	console := consoleHandle(t)

	original, _, _ := _procGetConsoleOutCP.Call()
	if ret, _, err := _procSetConsoleOutCP.Call(_codePageUTF8); ret == 0 {
		t.Fatalf("SetConsoleOutputCP(65001): %v", err)
	}
	t.Cleanup(func() { _, _, _ = _procSetConsoleOutCP.Call(original) })

	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	if _, err := SetupTelemetry(WithLogOutput(console)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	if err := ShutdownTelemetry(context.Background()); err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	if cp, _, _ := _procGetConsoleOutCP.Call(); cp != _codePageUTF8 {
		t.Errorf("console output code page is %d, want the %d the host set", cp, _codePageUTF8)
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
