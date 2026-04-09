// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// mutations5_test.go kills the final surviving gremlins mutations.
package logger

import (
	"runtime"
	"testing"
)

// TestComputeErrorFingerprintLimitedTo3Frames kills INCREMENT_DECREMENT at fingerprint.go:34:10.
//
// The count++ counter limits the loop to the first 3 frames.
// If mutated to count--, the loop never exits via count < 3 and processes ALL frames.
//
// Detection strategy:
//   - allPCs: all frames from a deep call stack (guaranteed >3 frames)
//   - firstThreePCs: same first 3 PCs only
//
// With count++ (original): both produce the same fingerprint because only the first
// 3 frames from allPCs are used.
//
// With count-- (mutation): firstThreePCs still exits via !more after 3 frames, but
// allPCs keeps going and includes many more frames → different fingerprint.
func TestComputeErrorFingerprintLimitedTo3Frames(t *testing.T) {
	allPCs := _deepCallerPCs()
	if len(allPCs) < 4 {
		t.Fatalf("expected >=4 frames for 3-frame limit test, got %d", len(allPCs))
	}

	// Using only the first 3 PCs (matches what count-limit should produce).
	first3 := allPCs[:3]
	fp3 := _computeErrorFingerprint("err", first3)
	fpAll := _computeErrorFingerprint("err", allPCs)

	// With count++ (original): allPCs uses only first 3 frames → same as first3.
	if fp3 != fpAll {
		t.Fatalf("count should limit to 3 frames: fp(first3)=%s fp(all)=%s", fp3, fpAll)
	}
}

// _deepCallerPCs returns PCs from a deliberately deep call stack (>3 frames).
func _deepCallerPCs() []uintptr {
	return _deepHelper1()
}
func _deepHelper1() []uintptr { return _deepHelper2() }
func _deepHelper2() []uintptr { return _deepHelper3() }
func _deepHelper3() []uintptr {
	buf := make([]uintptr, 64)
	n := runtime.Callers(0, buf) // skip=0 captures everything including runtime.Callers
	return buf[:n]
}

// TestComputeErrorFingerprintFileCheckDirect kills CONDITIONALS_NEGATION at fingerprint.go:27:22.
//
// Mutation: frame.File != "" → frame.File == "".
// With this mutation, only frames with EMPTY File are added.
// Go test frames always have non-empty File, so no frames would be added.
// That makes the fingerprint equal to fpNil.
//
// Detection: use a reference fingerprint from known PCs vs nil.
// We also verify by checking that the same fingerprint is stable.
func TestComputeErrorFingerprintFileCheckDirect(t *testing.T) {
	// Get a known set of PCs.
	pcs := make([]uintptr, 10)
	n := runtime.Callers(0, pcs) // skip=0 to include runtime.Callers itself
	pcs = pcs[:n]

	// Filter to only PCs that produce frames with non-empty File.
	frames := runtime.CallersFrames(pcs)
	var goodPCs []uintptr
	for _, pc := range pcs {
		singlePCS := []uintptr{pc}
		f := runtime.CallersFrames(singlePCS)
		frame, _ := f.Next()
		if frame.File != "" {
			goodPCs = append(goodPCs, pc)
		}
	}
	if len(goodPCs) == 0 {
		t.Skip("no frames with non-empty File found")
	}

	fpWithFile := _computeErrorFingerprint("err", goodPCs[:1]) // 1 frame with File != ""
	fpNil := _computeErrorFingerprint("err", nil)

	if fpWithFile == fpNil {
		t.Fatal("frame with non-empty File should produce different fingerprint than nil PCs")
	}

	_ = frames
}

// TestPIISanitizeSliceDepthDecrementStrong kills ARITHMETIC_BASE at pii.go:229:50.
//
// depth-1 in _sanitizeValue when dispatching to _sanitizeSlice. With mutation depth+1,
// slices recurse deeper than intended.
//
// Setup: slice → map → map → "xtoken" value with a rule matching the deep path.
// At depth=2, original (depth-1) passes depth=1 to _sanitizeSlice.
// _sanitizeSlice calls _sanitizeMap(inner, path, rules, 1).
// Inside that map, "nested" value is a map. _sanitizeValue("nested", ..., 1) returns early
// (depth<=1) → never recurses into "nested" → "xtoken" NOT reached by rule.
//
// With mutation (depth+1): passes depth=3 to _sanitizeSlice.
// _sanitizeSlice calls _sanitizeMap(inner, path, rules, 3).
// depth=3>1 → recurses into "nested" → "xtoken" IS reached and redacted.
func TestPIISanitizeSliceDepthDecrementStrong(t *testing.T) {
	SetPIIRules([]PIIRule{
		{Path: []string{"items", "nested", "xtoken"}, Mode: PIIModeRedact},
	})
	defer ResetPIIRules()

	payload := map[string]any{
		"items": []any{
			map[string]any{
				"nested": map[string]any{
					"xtoken": "deep-secret-value",
				},
			},
		},
	}

	// With depth=2 and depth-1 (original): _sanitizeSlice receives depth=1.
	// _sanitizeMap(inner, ["items"], rules, 1) → _sanitizeValue("nested", map, ..., 1)
	// → depth<=1, returns early → "xtoken" NOT reached → NOT redacted.
	//
	// With mutation (depth+1): _sanitizeSlice receives depth=3.
	// _sanitizeMap(inner, ["items"], rules, 3) → _sanitizeValue("nested", map, ..., 3)
	// → depth>1, recurses → _sanitizeMap(nested, ["items","nested"], rules, 2)
	// → rule matches ["items","nested","xtoken"] → "xtoken" IS redacted.
	result := SanitizePayload(payload, true, 2)
	items, ok := result["items"].([]any)
	if !ok {
		t.Fatalf("items should be []any, got %T", result["items"])
	}
	if len(items) == 0 {
		t.Fatal("items should not be empty")
	}
	item, ok := items[0].(map[string]any)
	if !ok {
		t.Fatalf("items[0] should be map, got %T", items[0])
	}
	nested, ok := item["nested"].(map[string]any)
	if !ok {
		t.Fatalf("items[0].nested should be map, got %T", item["nested"])
	}

	// At depth=2, "xtoken" should NOT be reached by the rule (depth-1 limits recursion).
	if nested["xtoken"] != "deep-secret-value" {
		t.Fatalf("xtoken should NOT be redacted at depth=2 with depth-1 in slice dispatch, got %v", nested["xtoken"])
	}
}
