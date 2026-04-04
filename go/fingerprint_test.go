// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"regexp"
	"runtime"
	"testing"
)

func TestExtractBasename_WithPath(t *testing.T) {
	got := _extractBasename("/path/to/myfile.go")
	if got != "myfile" {
		t.Errorf("expected 'myfile', got %q", got)
	}
}

func TestExtractBasename_WindowsPath(t *testing.T) {
	got := _extractBasename("C:\\path\\to\\myfile.go")
	if got != "myfile" {
		t.Errorf("expected 'myfile', got %q", got)
	}
}

func TestExtractBasename_NoExtension(t *testing.T) {
	got := _extractBasename("/path/to/myfile")
	if got != "myfile" {
		t.Errorf("expected 'myfile', got %q", got)
	}
}

func TestExtractBasename_NoPath(t *testing.T) {
	got := _extractBasename("myfile.go")
	if got != "myfile" {
		t.Errorf("expected 'myfile', got %q", got)
	}
}

func TestExtractBasename_Uppercased(t *testing.T) {
	got := _extractBasename("/path/MyFile.Go")
	if got != "myfile" {
		t.Errorf("expected lowercase 'myfile', got %q", got)
	}
}

func TestExtractFuncName_Qualified(t *testing.T) {
	got := _extractFuncName("github.com/provide-io/provide-telemetry/go.TestFunc")
	if got != "TestFunc" {
		t.Errorf("expected 'TestFunc', got %q", got)
	}
}

func TestExtractFuncName_NoQualifier(t *testing.T) {
	got := _extractFuncName("simpleFunc")
	if got != "simpleFunc" {
		t.Errorf("expected 'simpleFunc', got %q", got)
	}
}

func TestComputeErrorFingerprint_WithFrames(t *testing.T) {
	// Capture real program counters so frame traversal is exercised.
	pcs := make([]uintptr, 8)
	n := runtime.Callers(1, pcs)
	pcs = pcs[:n]

	fp := _computeErrorFingerprint("RuntimeError", pcs)
	if len(fp) != 12 {
		t.Fatalf("expected 12-char fingerprint, got %d: %q", len(fp), fp)
	}
	matched, _ := regexp.MatchString(`^[0-9a-f]{12}$`, fp)
	if !matched {
		t.Errorf("fingerprint must be lowercase hex: %q", fp)
	}
}

func TestShortHash12_Format(t *testing.T) {
	h := _shortHash12("test-input")
	if len(h) != 12 {
		t.Fatalf("expected 12 chars, got %d: %q", len(h), h)
	}
	matched, _ := regexp.MatchString(`^[0-9a-f]{12}$`, h)
	if !matched {
		t.Errorf("hash must be lowercase hex: %q", h)
	}
}

func TestComputeErrorFingerprint_InvalidPCs(t *testing.T) {
	// A slice with a zero/invalid PC triggers the frame.Function == "" && !more early break.
	pcs := []uintptr{0}
	fp := _computeErrorFingerprint("ValueError", pcs)
	if len(fp) != 12 {
		t.Fatalf("expected 12-char fingerprint even with invalid PCs, got %d: %q", len(fp), fp)
	}
}
