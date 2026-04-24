// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"regexp"
	"testing"
	"unsafe"
)

// BenchmarkCustomPIIPatterns_HotPath measures the per-call cost of
// _customPIIPatterns, which is invoked on every log record by the telemetry
// handler's applyPII step. Post-caching, this must be a single atomic load
// plus a pointer deref — no map allocation, no RWMutex, no regex compile.
func BenchmarkCustomPIIPatterns_HotPath(b *testing.B) {
	_resetSecretPatterns()
	b.Cleanup(_resetSecretPatterns)

	RegisterSecretPattern("bench-a", regexp.MustCompile(`AAA-[0-9]{10,}`))
	RegisterSecretPattern("bench-b", regexp.MustCompile(`BBB-[a-f]{10,}`))

	b.ResetTimer()
	b.ReportAllocs()
	for b.Loop() {
		_ = _customPIIPatterns()
	}
}

// BenchmarkCustomPIIPatterns_NoPatterns_HotPath measures the nil-snapshot
// fast path (no patterns registered) — the common case in production.
func BenchmarkCustomPIIPatterns_NoPatterns_HotPath(b *testing.B) {
	_resetSecretPatterns()
	b.Cleanup(_resetSecretPatterns)

	b.ResetTimer()
	b.ReportAllocs()
	for b.Loop() {
		_ = _customPIIPatterns()
	}
}

// TestCustomPIIPatterns_SnapshotReusedAcrossCalls pins the caching contract:
// two consecutive reads without an intervening RegisterSecretPattern /
// _resetSecretPatterns MUST return the same underlying map header. This
// guarantees the hot path neither recompiles the regexes nor re-copies the
// map on every log record.
func TestCustomPIIPatterns_SnapshotReusedAcrossCalls(t *testing.T) {
	_resetSecretPatterns()
	t.Cleanup(_resetSecretPatterns)

	RegisterSecretPattern("same-snapshot", regexp.MustCompile(`SNAP-[0-9]+`))

	first := _customPIIPatterns()
	second := _customPIIPatterns()
	if first == nil || second == nil {
		t.Fatal("expected non-nil snapshot after RegisterSecretPattern")
	}
	// The cached snapshot is shared by reference: compare the underlying
	// map headers via unsafe.Pointer to assert identity (regular map
	// equality is not defined in Go).
	firstPtr := *(*unsafe.Pointer)(unsafe.Pointer(&first))
	secondPtr := *(*unsafe.Pointer)(unsafe.Pointer(&second))
	if firstPtr != secondPtr {
		t.Fatal("expected _customPIIPatterns to return the cached snapshot; got a fresh map each call")
	}
}

// TestCustomPIIPatterns_SnapshotInvalidatedOnRegister verifies the snapshot
// is replaced (not reused) when a new pattern is registered — the cache must
// not go stale.
func TestCustomPIIPatterns_SnapshotInvalidatedOnRegister(t *testing.T) {
	_resetSecretPatterns()
	t.Cleanup(_resetSecretPatterns)

	RegisterSecretPattern("initial", regexp.MustCompile(`INIT-[0-9]+`))
	before := _customPIIPatterns()
	if _, ok := before["initial"]; !ok {
		t.Fatal("expected 'initial' key in snapshot before re-register")
	}

	RegisterSecretPattern("added", regexp.MustCompile(`ADD-[0-9]+`))
	after := _customPIIPatterns()
	if _, ok := after["added"]; !ok {
		t.Fatal("expected 'added' key in snapshot after RegisterSecretPattern")
	}
	// Snapshots must differ by identity — stale snapshot would miss 'added'.
	beforePtr := *(*unsafe.Pointer)(unsafe.Pointer(&before))
	afterPtr := *(*unsafe.Pointer)(unsafe.Pointer(&after))
	if beforePtr == afterPtr {
		t.Fatal("expected snapshot to be replaced after RegisterSecretPattern")
	}
}

// TestCustomPIIPatterns_SnapshotClearedOnReset verifies _resetSecretPatterns
// publishes a nil snapshot so the hot path short-circuits.
func TestCustomPIIPatterns_SnapshotClearedOnReset(t *testing.T) {
	RegisterSecretPattern("temp-pat", regexp.MustCompile(`TEMP-[0-9]+`))
	if got := _customPIIPatterns(); got == nil {
		t.Fatal("expected non-nil snapshot after RegisterSecretPattern")
	}

	_resetSecretPatterns()
	if got := _customPIIPatterns(); got != nil {
		t.Fatalf("expected nil snapshot after _resetSecretPatterns, got %v", got)
	}
}
