// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"sync"
	"testing"
	"time"
)

func TestGuardAttributes_NoLimit_PassThrough(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	input := map[string]string{"env": "production", "region": "us-east-1"}
	got := GuardAttributes(input)

	if got["env"] != "production" {
		t.Errorf("env: want %q, got %q", "production", got["env"])
	}
	if got["region"] != "us-east-1" {
		t.Errorf("region: want %q, got %q", "us-east-1", got["region"])
	}
}

func TestGuardAttributes_SeenValue_PassThrough(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("user_id", CardinalityLimit{MaxValues: 3, TTLSeconds: 60})

	// First call: adds value to cache.
	got1 := GuardAttributes(map[string]string{"user_id": _testAlice})
	if got1["user_id"] != _testAlice {
		t.Fatalf("first call: want %q, got %q", _testAlice, got1["user_id"])
	}

	// Second call: same value is already cached — must not overflow.
	got2 := GuardAttributes(map[string]string{"user_id": _testAlice})
	if got2["user_id"] != _testAlice {
		t.Errorf("second call (seen): want %q, got %q", _testAlice, got2["user_id"])
	}
}

func TestGuardAttributes_UnderLimit_Added(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("status", CardinalityLimit{MaxValues: 5, TTLSeconds: 60})

	for _, v := range []string{"ok", "error", "timeout"} {
		got := GuardAttributes(map[string]string{"status": v})
		if got["status"] != v {
			t.Errorf("status=%q: want %q, got %q", v, v, got["status"])
		}
	}
}

func TestGuardAttributes_AtLimit_Overflow(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("tenant_id", CardinalityLimit{MaxValues: 2, TTLSeconds: 60})

	// Fill to capacity.
	r1 := GuardAttributes(map[string]string{"tenant_id": "t1"})
	if r1["tenant_id"] != "t1" {
		t.Fatalf("slot 1: want %q, got %q", "t1", r1["tenant_id"])
	}
	r2 := GuardAttributes(map[string]string{"tenant_id": "t2"})
	if r2["tenant_id"] != "t2" {
		t.Fatalf("slot 2: want %q, got %q", "t2", r2["tenant_id"])
	}

	// New value when at capacity.
	r3 := GuardAttributes(map[string]string{"tenant_id": "t3"})
	if r3["tenant_id"] != _overflowValue {
		t.Errorf("over limit: want %q, got %q", _overflowValue, r3["tenant_id"])
	}
}

func TestGuardAttributes_TTLExpiry_SlotFreed(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("session", CardinalityLimit{MaxValues: 1, TTLSeconds: 0.01}) // 10ms TTL

	// Fill the single slot.
	r1 := GuardAttributes(map[string]string{"session": "s1"})
	if r1["session"] != "s1" {
		t.Fatalf("slot 1: want %q, got %q", "s1", r1["session"])
	}

	// New value immediately overflows.
	r2 := GuardAttributes(map[string]string{"session": "s2"})
	if r2["session"] != _overflowValue {
		t.Fatalf("before TTL: want %q, got %q", _overflowValue, r2["session"])
	}

	// Wait for TTL to expire.
	time.Sleep(20 * time.Millisecond)

	// After expiry the slot is free — new value should be accepted.
	r3 := GuardAttributes(map[string]string{"session": "s2"})
	if r3["session"] != "s2" {
		t.Errorf("after TTL: want %q, got %q", "s2", r3["session"])
	}
}

func TestSetGetCardinalityLimit_RoundTrip(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	want := CardinalityLimit{MaxValues: 42, TTLSeconds: 3.14}
	SetCardinalityLimit("foo", want)
	got := GetCardinalityLimit("foo")

	if got.MaxValues != want.MaxValues {
		t.Errorf("MaxValues: want %d, got %d", want.MaxValues, got.MaxValues)
	}
	if got.TTLSeconds != want.TTLSeconds {
		t.Errorf("TTLSeconds: want %v, got %v", want.TTLSeconds, got.TTLSeconds)
	}
}

func TestGetCardinalityLimit_Unknown_ZeroValue(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	got := GetCardinalityLimit("nonexistent")
	if got.MaxValues != 0 || got.TTLSeconds != 0 {
		t.Errorf("unknown key: want zero CardinalityLimit, got %+v", got)
	}
}

func TestGuardAttributes_MultipleKeys_Independent(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("color", CardinalityLimit{MaxValues: 1, TTLSeconds: 60})
	SetCardinalityLimit("size", CardinalityLimit{MaxValues: 1, TTLSeconds: 60})

	// Fill both keys.
	GuardAttributes(map[string]string{"color": "red", "size": "large"})

	// New values for both should overflow independently.
	result := GuardAttributes(map[string]string{"color": "blue", "size": "small"})

	if result["color"] != _overflowValue {
		t.Errorf("color: want %q, got %q", _overflowValue, result["color"])
	}
	if result["size"] != _overflowValue {
		t.Errorf("size: want %q, got %q", _overflowValue, result["size"])
	}
}

func TestGuardAttributes_Concurrent(t *testing.T) {
	_resetCardinalityLimits()
	t.Cleanup(_resetCardinalityLimits)

	SetCardinalityLimit("ckey", CardinalityLimit{MaxValues: 10, TTLSeconds: 60})

	const goroutines = 50
	const iterations = 100

	var wg sync.WaitGroup
	wg.Add(goroutines)
	for i := 0; i < goroutines; i++ {
		go func(id int) {
			defer wg.Done()
			for j := 0; j < iterations; j++ {
				val := fmt.Sprintf("v%d", j%20) // 20 distinct values, limit=10 → half overflow
				result := GuardAttributes(map[string]string{"ckey": val})
				v := result["ckey"]
				if v != val && v != _overflowValue {
					t.Errorf("unexpected value %q for input %q", v, val)
				}
			}
		}(i)
	}
	wg.Wait()
}
