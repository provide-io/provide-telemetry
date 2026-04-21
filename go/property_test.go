// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"fmt"
	"math"
	"net/http"
	"strings"
	"testing"
)

// ── Sampling Properties ─────────────────────────────────────────────────────

func resetSampling(t *testing.T) {
	t.Helper()
	_resetSamplingPolicies()
	t.Cleanup(_resetSamplingPolicies)
}

func TestPropertySamplingRateZeroNeverSamples(t *testing.T) {
	resetSampling(t)
	_, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.0})
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 1000; i++ {
		sampled, err := ShouldSample(signalLogs, fmt.Sprintf("event-%d", i))
		if err != nil {
			t.Fatal(err)
		}
		if sampled {
			t.Fatal("rate=0.0 should never sample")
		}
	}
}

func TestPropertySamplingRateOneAlwaysSamples(t *testing.T) {
	resetSampling(t)
	_, err := SetSamplingPolicy(signalTraces, SamplingPolicy{DefaultRate: 1.0})
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 1000; i++ {
		sampled, err := ShouldSample(signalTraces, fmt.Sprintf("event-%d", i))
		if err != nil {
			t.Fatal(err)
		}
		if !sampled {
			t.Fatal("rate=1.0 should always sample")
		}
	}
}

func TestPropertySamplingPolicyRoundTrip(t *testing.T) {
	resetSampling(t)
	signals := []string{signalLogs, signalTraces, signalMetrics}
	for _, sig := range signals {
		want := SamplingPolicy{
			DefaultRate: 0.42,
			Overrides:   map[string]float64{"special": 0.99},
		}
		_, err := SetSamplingPolicy(sig, want)
		if err != nil {
			t.Fatalf("SetSamplingPolicy(%s): %v", sig, err)
		}
		got, err := GetSamplingPolicy(sig)
		if err != nil {
			t.Fatalf("GetSamplingPolicy(%s): %v", sig, err)
		}
		if got.DefaultRate != want.DefaultRate {
			t.Fatalf("signal %s: DefaultRate = %g, want %g", sig, got.DefaultRate, want.DefaultRate)
		}
		if got.Overrides["special"] != want.Overrides["special"] {
			t.Fatalf("signal %s: Override mismatch", sig)
		}
	}
}

func TestPropertySamplingUnknownSignalErrors(t *testing.T) {
	resetSampling(t)
	badSignals := []string{"", "unknown", "log", "LOGS", "metric", "trace"}
	for _, sig := range badSignals {
		_, err := SetSamplingPolicy(sig, SamplingPolicy{DefaultRate: 0.5})
		if err == nil {
			t.Fatalf("expected error for signal %q", sig)
		}
		_, err = GetSamplingPolicy(sig)
		if err == nil {
			t.Fatalf("expected error for signal %q", sig)
		}
		_, err = ShouldSample(sig, "test")
		if err == nil {
			t.Fatalf("expected error for signal %q", sig)
		}
	}
}

func TestPropertySamplingRateClamped(t *testing.T) {
	resetSampling(t)
	cases := []struct {
		input float64
		want  float64
	}{
		{-1.0, 0.0},
		{2.5, 1.0},
		{math.NaN(), 0.0},
		{0.5, 0.5},
		{0.0, 0.0},
		{1.0, 1.0},
	}
	for _, tc := range cases {
		got, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: tc.input})
		if err != nil {
			t.Fatal(err)
		}
		if got.DefaultRate != tc.want {
			t.Fatalf("clamp(%g) = %g, want %g", tc.input, got.DefaultRate, tc.want)
		}
	}
}

// ── PII Properties ──────────────────────────────────────────────────────────

func resetPIIForProp(t *testing.T) {
	t.Helper()
	_resetPIIRules()
	_resetSecretPatterns()
	t.Cleanup(_resetPIIRules)
	t.Cleanup(_resetSecretPatterns)
}

func TestPropertyPIISensitiveKeysAlwaysRedacted(t *testing.T) {
	resetPIIForProp(t)
	sensitiveKeys := []string{
		"password", "token", "api_key", "secret", "authorization",
		"credential", "private_key", "ssn", "credit_card",
	}
	for _, key := range sensitiveKeys {
		payload := map[string]any{key: "some-value-" + key}
		result := SanitizePayload(payload, true, 0)
		if result[key] != _piiRedacted {
			t.Fatalf("expected key %q to be redacted, got %v", key, result[key])
		}
	}
}

func TestPropertyPIIDisabledReturnsOriginalValues(t *testing.T) {
	resetPIIForProp(t)
	sensitiveKeys := []string{"password", "token", "secret"}
	for _, key := range sensitiveKeys {
		val := "original-" + key
		payload := map[string]any{key: val}
		result := SanitizePayload(payload, false, 0)
		if result[key] != val {
			t.Fatalf("disabled PII: key %q = %v, want %v", key, result[key], val)
		}
	}
}

func TestPropertyPIIAWSKeyAlwaysDetected(t *testing.T) {
	resetPIIForProp(t)
	// AWS access key IDs start with AKIA followed by 16 alphanumeric chars.
	// Construct test values programmatically to avoid triggering GitHub push protection.
	prefix := "AKI" + "A"
	awsKeys := []string{
		prefix + "AAAAAAAAAAAAAAAA",
		prefix + "BBBBBBBBBBBBBBBB",
		prefix + "1234567890123456",
	}
	for _, ak := range awsKeys {
		payload := map[string]any{"data": ak}
		result := SanitizePayload(payload, true, 0)
		if result["data"] == ak {
			t.Fatalf("expected AWS key %q to be redacted in value", ak)
		}
	}
}

func TestPropertyPIISanitizeNeverMutatesInput(t *testing.T) {
	resetPIIForProp(t)
	payload := map[string]any{
		"password": "hunter2", // pragma: allowlist secret
		"safe":     "hello",
	}
	origPassword := payload["password"]
	origSafe := payload["safe"]
	_ = SanitizePayload(payload, true, 0)
	if payload["password"] != origPassword { // pragma: allowlist secret
		t.Fatal("SanitizePayload mutated original map (password)") // pragma: allowlist secret
	}
	if payload["safe"] != origSafe {
		t.Fatal("SanitizePayload mutated original map (safe)")
	}
}

// ── Schema Properties ───────────────────────────────────────────────────────

func TestPropertyEventValidSegmentCounts(t *testing.T) {
	// DAS (3 segments) and DARS (4 segments) should always succeed with valid segments.
	SetStrictSchema(true)
	t.Cleanup(func() { SetStrictSchema(false) })

	validSegments := [][]string{
		{"auth", "login", "success"},
		{"user", "profile", "update", "complete"},
	}
	for _, segs := range validSegments {
		_, err := Event(segs...)
		if err != nil {
			t.Fatalf("Event(%v) unexpected error: %v", segs, err)
		}
	}
}

func TestPropertyEventInvalidSegmentCounts(t *testing.T) {
	// Event rejects < 3 or > 4 segments.
	SetStrictSchema(false)
	t.Cleanup(func() { SetStrictSchema(false) })

	invalidCounts := [][]string{
		{},
		{"one"},
		{"one", "two"},
		{"a", "b", "c", "d", "e"},
	}
	for _, segs := range invalidCounts {
		_, err := Event(segs...)
		if err == nil {
			t.Fatalf("Event(%v) should have failed for %d segments", segs, len(segs))
		}
	}
}

func TestPropertyEventNameValidSegmentRange(t *testing.T) {
	// EventName accepts 3-5 segments.
	SetStrictSchema(false)
	t.Cleanup(func() { SetStrictSchema(false) })

	for n := 3; n <= 5; n++ {
		segs := make([]string, n)
		for i := range segs {
			segs[i] = fmt.Sprintf("seg%d", i)
		}
		_, err := EventName(segs...)
		if err != nil {
			t.Fatalf("EventName with %d segments failed: %v", n, err)
		}
	}
}

func TestPropertyEventHyphensRejectedInStrictMode(t *testing.T) {
	SetStrictSchema(true)
	t.Cleanup(func() { SetStrictSchema(false) })

	_, err := Event("auth", "log-in", "success")
	if err == nil {
		t.Fatal("expected hyphens to be rejected in strict mode")
	}
}

func TestPropertyEventHyphensAllowedInLenientMode(t *testing.T) {
	SetStrictSchema(false)
	t.Cleanup(func() { SetStrictSchema(false) })

	_, err := Event("auth", "log-in", "success")
	if err != nil {
		t.Fatalf("hyphens should be allowed in lenient mode: %v", err)
	}
}

// ── Propagation Properties ──────────────────────────────────────────────────

func TestPropertyParseBaggageNeverEmptyKey(t *testing.T) {
	inputs := []string{
		"key=value",
		"a=1,b=2",
		"k1=v1;prop=x,k2=v2",
		",,,",
		"=nope",
		"",
		"a=1,,b=2",
		"  spaced = val  ",
	}
	for _, input := range inputs {
		result := ParseBaggage(input)
		for k := range result {
			if k == "" {
				t.Fatalf("ParseBaggage(%q) produced empty key", input)
			}
		}
	}
}

func TestPropertyExtractW3CValidTraceparentParses(t *testing.T) {
	// Valid traceparent: version-traceid(32hex)-spanid(16hex)-flags(2hex)
	validTraceparents := []string{
		"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
		"00-abcdef1234567890abcdef1234567890-1234567890abcdef-00",
	}
	for _, tp := range validTraceparents {
		headers := http.Header{}
		headers.Set("Traceparent", tp)
		ctx := ExtractW3CContext(headers)
		if ctx.TraceID == "" {
			t.Fatalf("valid traceparent %q: TraceID is empty", tp)
		}
		if ctx.SpanID == "" {
			t.Fatalf("valid traceparent %q: SpanID is empty", tp)
		}
		if len(ctx.TraceID) != 32 {
			t.Fatalf("TraceID length = %d, want 32", len(ctx.TraceID))
		}
		if len(ctx.SpanID) != 16 {
			t.Fatalf("SpanID length = %d, want 16", len(ctx.SpanID))
		}
	}
}

func TestPropertyExtractW3CInvalidTraceparentEmpty(t *testing.T) {
	invalidTraceparents := []string{
		"",
		"not-a-traceparent",
		"00-0000000000000000000000000000000-00f067aa0ba902b7-01",  // too short trace ID
		"00-00000000000000000000000000000000-00f067aa0ba902b7-01", // all-zero trace ID
		"ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01", // invalid version
	}
	for _, tp := range invalidTraceparents {
		headers := http.Header{}
		if tp != "" {
			headers.Set("Traceparent", tp)
		}
		ctx := ExtractW3CContext(headers)
		if ctx.TraceID != "" {
			t.Fatalf("invalid traceparent %q: expected empty TraceID, got %q", tp, ctx.TraceID)
		}
	}
}

// ── Config Properties ───────────────────────────────────────────────────────

func TestPropertyParseEnvBoolValidValues(t *testing.T) {
	truthy := []string{"1", "true", "yes", "on", "TRUE", "Yes", " true ", " ON "}
	for _, v := range truthy {
		got, err := parseEnvBool(v, false, "test")
		if err != nil {
			t.Fatalf("parseEnvBool(%q): unexpected error: %v", v, err)
		}
		if !got {
			t.Fatalf("parseEnvBool(%q) = false, want true", v)
		}
	}
	falsy := []string{"0", "false", "no", "off", "FALSE", "No", " off "}
	for _, v := range falsy {
		got, err := parseEnvBool(v, true, "test")
		if err != nil {
			t.Fatalf("parseEnvBool(%q): unexpected error: %v", v, err)
		}
		if got {
			t.Fatalf("parseEnvBool(%q) = true, want false", v)
		}
	}
}

func TestPropertyParseEnvBoolEmptyReturnsDefault(t *testing.T) {
	for _, def := range []bool{true, false} {
		got, err := parseEnvBool("", def, "test")
		if err != nil {
			t.Fatal(err)
		}
		if got != def {
			t.Fatalf("parseEnvBool('', %v) = %v", def, got)
		}
	}
}

func TestPropertyParseEnvBoolInvalidReturnsError(t *testing.T) {
	invalids := []string{"maybe", "2", "yep", "nah", "enabled", "disabled"}
	for _, v := range invalids {
		_, err := parseEnvBool(v, false, "test")
		if err == nil {
			t.Fatalf("parseEnvBool(%q) should return error", v)
		}
	}
}

// ── Fuzz Targets ────────────────────────────────────────────────────────────

func FuzzParseEnvBool(f *testing.F) {
	f.Add("true")
	f.Add("false")
	f.Add("1")
	f.Add("0")
	f.Add("")
	f.Add("GARBAGE")
	f.Add("  yes  ")
	f.Fuzz(func(t *testing.T, input string) {
		// Must never panic. Error is acceptable for invalid input.
		_, _ = parseEnvBool(input, false, "fuzz_field")
	})
}

func FuzzParseBaggage(f *testing.F) {
	f.Add("key=value")
	f.Add("a=1,b=2;prop=x")
	f.Add("")
	f.Add(",,,")
	f.Add("=nokey")
	f.Add("k1=v1,k2=v2,k3=v3")
	f.Add(strings.Repeat("x=y,", 100))
	f.Fuzz(func(t *testing.T, input string) {
		result := ParseBaggage(input)
		for k := range result {
			if k == "" {
				t.Error("empty key in ParseBaggage result")
			}
		}
	})
}

func FuzzSanitizePayload(f *testing.F) {
	f.Add("password", "secret123") // pragma: allowlist secret
	f.Add("safe_key", "safe_value")
	f.Add("", "")
	f.Add("api_key", "test-api-key-value")
	f.Fuzz(func(t *testing.T, key, value string) {
		// Must never panic on any key/value combination.
		payload := map[string]any{key: value}
		_ = SanitizePayload(payload, true, 0)
		_ = SanitizePayload(payload, false, 0)
	})
}

func FuzzExtractW3CContext(f *testing.F) {
	f.Add("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
	f.Add("")
	f.Add("not-valid")
	f.Add("00-00000000000000000000000000000000-0000000000000000-00")
	f.Add(strings.Repeat("a", 600))
	f.Fuzz(func(t *testing.T, traceparent string) {
		headers := http.Header{}
		headers.Set("Traceparent", traceparent)
		ctx := ExtractW3CContext(headers)
		// If parsed successfully, IDs must have correct lengths.
		if ctx.TraceID != "" && len(ctx.TraceID) != 32 {
			t.Errorf("TraceID length = %d, want 32", len(ctx.TraceID))
		}
		if ctx.SpanID != "" && len(ctx.SpanID) != 16 {
			t.Errorf("SpanID length = %d, want 16", len(ctx.SpanID))
		}
	})
}

func FuzzValidateEventName(f *testing.F) {
	f.Add("auth.login.success")
	f.Add("a.b.c.d.e")
	f.Add("")
	f.Add("one")
	f.Add("a.b")
	f.Add("auth.log-in.success")
	f.Fuzz(func(t *testing.T, name string) {
		// Must never panic.
		_ = ValidateEventName(name)
	})
}
