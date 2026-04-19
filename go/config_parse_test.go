// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"errors"
	"testing"
)

// ---- OTLP header parsing ----

func TestParseOTLPHeaders_Normal(t *testing.T) {
	// '+' is preserved as a literal character; use %20 for spaces.
	got := parseOTLPHeaders("Authorization=Bearer%20token,X-Tenant=abc")
	if got["Authorization"] != "Bearer token" {
		t.Errorf("Authorization: got %q", got["Authorization"])
	}
	if got["X-Tenant"] != "abc" {
		t.Errorf("X-Tenant: got %q", got["X-Tenant"])
	}
}

func TestParseOTLPHeaders_URLEncoded(t *testing.T) {
	got := parseOTLPHeaders("my%20key=my%20value")
	if got["my key"] != "my value" {
		t.Errorf("URL-decoded: got %v", got)
	}
}

func TestParseOTLPHeaders_Malformed_Skipped(t *testing.T) {
	// pair without '=' should be skipped
	got := parseOTLPHeaders("no-equals,key=val")
	if _, ok := got["no-equals"]; ok {
		t.Error("malformed pair should be skipped")
	}
	if got["key"] != "val" {
		t.Errorf("valid pair: got %q", got["key"])
	}
}

func TestParseOTLPHeaders_EmptyKey_Skipped(t *testing.T) {
	got := parseOTLPHeaders("=value,key=val")
	if _, ok := got[""]; ok {
		t.Error("empty key should be skipped")
	}
	if got["key"] != "val" {
		t.Errorf("valid pair: got %q", got["key"])
	}
}

func TestParseOTLPHeaders_InvalidURLEncodedValue_Skipped(t *testing.T) {
	// A percent sign followed by invalid hex causes url.QueryUnescape to fail on the value.
	got := parseOTLPHeaders("key=%ZZ,other=ok")
	if _, ok := got["key"]; ok {
		t.Error("pair with invalid URL-encoded value should be skipped")
	}
	if got["other"] != "ok" {
		t.Errorf("valid pair: got %q", got["other"])
	}
}

func TestParseOTLPHeaders_InvalidURLEncodedKey_Skipped(t *testing.T) {
	// A percent sign followed by invalid hex in the key should also be skipped.
	got := parseOTLPHeaders("%ZZ=value,other=ok")
	if _, ok := got["%ZZ"]; ok {
		t.Error("pair with invalid URL-encoded key should be skipped")
	}
	if got["other"] != "ok" {
		t.Errorf("valid pair: got %q", got["other"])
	}
}

func TestParseOTLPHeaders_SingleCharKey_Accepted(t *testing.T) {
	got := parseOTLPHeaders("k=v")
	if got["k"] != "v" {
		t.Errorf("single-char key: want k=v, got %v", got)
	}
}

func TestParseOTLPHeaders_Empty(t *testing.T) {
	got := parseOTLPHeaders("")
	if len(got) != 0 {
		t.Errorf("empty input: got %v", got)
	}
}

// ---- Module levels parsing ----

func TestParseModuleLevels_Valid(t *testing.T) {
	got, err := parseModuleLevels("myapp=DEBUG,asyncio=WARNING")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got["myapp"] != testDebugLevel {
		t.Errorf("myapp: got %q", got["myapp"])
	}
	if got["asyncio"] != "WARNING" {
		t.Errorf("asyncio: got %q", got["asyncio"])
	}
}

func TestParseModuleLevels_MixedCase(t *testing.T) {
	got, err := parseModuleLevels("pkg=info")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got["pkg"] != "INFO" {
		t.Errorf("level should be normalised to INFO, got %q", got["pkg"])
	}
}

func TestParseModuleLevels_SingleCharModule_Accepted(t *testing.T) {
	got, err := parseModuleLevels("a=DEBUG")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got["a"] != testDebugLevel {
		t.Errorf("single-char module: got %q, want %q", got["a"], testDebugLevel)
	}
}

func TestParseModuleLevels_MalformedPair_Skipped(t *testing.T) {
	got, err := parseModuleLevels("no-equals,pkg=DEBUG")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, ok := got["no-equals"]; ok {
		t.Error("malformed pair should be skipped")
	}
	if got["pkg"] != testDebugLevel {
		t.Errorf("valid pair: got %q", got["pkg"])
	}
}

func TestParseModuleLevels_EmptyModuleName_Skipped(t *testing.T) {
	// "=DEBUG" has an '=' but empty module name — should be skipped.
	got, err := parseModuleLevels("=DEBUG,pkg=INFO")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, ok := got[""]; ok {
		t.Error("empty module name should be skipped")
	}
	if got["pkg"] != "INFO" {
		t.Errorf("valid pair: got %q", got["pkg"])
	}
}

func TestParseModuleLevels_Empty(t *testing.T) {
	got, err := parseModuleLevels("")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("expected empty map, got %v", got)
	}
}

func TestParseModuleLevels_InvalidLevel_Error(t *testing.T) {
	_, err := parseModuleLevels("pkg=BADLEVEL")
	if err == nil {
		t.Fatal("expected error for invalid level")
	}
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Errorf("expected *ConfigurationError, got %T", err)
	}
}

// ---- Log level normalisation coverage ----

func TestNormalizeLevel_AllValid(t *testing.T) {
	cases := []struct{ in, want string }{
		{"TRACE", "TRACE"}, {"trace", "TRACE"},
		{"DEBUG", "DEBUG"}, {"debug", "DEBUG"},
		{"INFO", "INFO"}, {"info", "INFO"},
		{"WARNING", "WARNING"}, {"warning", "WARNING"},
		{"ERROR", "ERROR"}, {"error", "ERROR"},
		{"CRITICAL", "CRITICAL"}, {"critical", "CRITICAL"},
	}
	for _, tc := range cases {
		got, err := normalizeLevel(tc.in)
		if err != nil {
			t.Errorf("normalizeLevel(%q): unexpected error %v", tc.in, err)
		}
		if got != tc.want {
			t.Errorf("normalizeLevel(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

func TestNormalizeLevel_Invalid(t *testing.T) {
	_, err := normalizeLevel("VERBOSE")
	if err == nil {
		t.Fatal("expected error")
	}
	var cfgErr *ConfigurationError
	if !errors.As(err, &cfgErr) {
		t.Errorf("expected *ConfigurationError, got %T", err)
	}
}

// ---- firstNonEmpty ----

func TestFirstNonEmpty(t *testing.T) {
	if firstNonEmpty("", "b", "c") != "b" {
		t.Error("should return first non-empty")
	}
	if firstNonEmpty("", "") != "" {
		t.Error("all empty should return empty")
	}
	if firstNonEmpty("a", "b") != "a" {
		t.Error("should return first when first non-empty")
	}
}

// ---- splitTrimmed ----

func TestSplitTrimmed_Normal(t *testing.T) {
	got := splitTrimmed(" a , b , c ", ",")
	want := []string{"a", "b", "c"}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("[%d]: got %q, want %q", i, got[i], want[i])
		}
	}
}

func TestSplitTrimmed_EmptyElements_Skipped(t *testing.T) {
	got := splitTrimmed(",a,,b,", ",")
	if len(got) != 2 || got[0] != "a" || got[1] != "b" {
		t.Errorf("got %v", got)
	}
}
