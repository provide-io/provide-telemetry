// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"math"
	"net/url"
	"strings"
	"testing"
	"unicode/utf8"
)

// Coverage-guided fuzz targets for config parsing / redaction surfaces.
// Local stand-in for OSS-Fuzz native Go targets:
//
//	make -C go fuzz FUZZTIME=30s
//	go test . -run='^$' -fuzz=FuzzParseOTLPHeaders -fuzztime=30s

// FuzzParseOTLPHeaders: never panics; every returned key is non-empty.
func FuzzParseOTLPHeaders(f *testing.F) {
	for _, s := range []string{
		"",
		"Authorization=Bearer%20token",
		"Authorization=Bearer token",
		"a=b,c=d",
		"=",
		"key=",
		"=value",
		"a=b=c",
		"x-api+json=1",
		"k=%ZZ",
		strings.Repeat("A", 100_000),
		"Authorization=Bearer x\r\nX-Injected: yes",
		"a=1,b=2,c=3,d=4,e=5",
	} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, raw string) {
		h := parseOTLPHeaders(raw)
		if h == nil {
			t.Fatal("parseOTLPHeaders returned nil map")
		}
		for k, v := range h {
			if k == "" {
				t.Fatalf("empty key in result for input %q (val=%q)", raw, v)
			}
		}
	})
}

// FuzzMaskEndpointURL: never panics; never echoes a non-empty password.
func FuzzMaskEndpointURL(f *testing.F) {
	for _, s := range []string{
		"",
		"https://otel.example.com/v1/traces",
		"https://user:p4ssw0rd@otel.example.com/v1/traces",
		"https://user:s3cr3t@otel.example.com:4318/v1/traces",
		"http://user@host:4318",
		"not a url",
		"https://u:secret@host/path?q=1",
	} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, raw string) {
		if !utf8.ValidString(raw) {
			_ = maskEndpointURL(raw)
			return
		}
		got := maskEndpointURL(raw)
		u, err := url.Parse(raw)
		if err != nil || u.User == nil {
			if got != raw {
				// maskEndpointURL returns raw when no password userinfo
				if u != nil && u.User != nil {
					if pass, ok := u.User.Password(); !ok || pass == "" {
						if got != raw {
							t.Fatalf("username-only changed: in=%q out=%q", raw, got)
						}
					}
				} else if got != raw {
					t.Fatalf("changed input without userinfo password: in=%q out=%q", raw, got)
				}
			}
			return
		}
		pass, hasPass := u.User.Password()
		if !hasPass || pass == "" {
			if got != raw {
				t.Fatalf("username-only should pass through: in=%q out=%q", raw, got)
			}
			return
		}
		// Password-bearing URL must change, and user:pass@ must not survive.
		// (Do not use strings.Contains(got, pass): password "*" matches "****".)
		if got == raw {
			t.Fatalf("password-bearing URL left unmasked: %q", raw)
		}
		name := u.User.Username()
		if strings.Contains(got, name+":"+pass+"@") {
			t.Fatalf("user:pass@ leaked: in=%q out=%q", raw, got)
		}
		if !strings.Contains(got, ":****@") && !strings.Contains(got, "****") {
			t.Fatalf("expected **** mask: in=%q out=%q", raw, got)
		}
	})
}

// FuzzValidateRate: only finite [0,1] values succeed.
func FuzzValidateRate(f *testing.F) {
	for _, v := range []float64{
		0, 1, 0.5, 0.1, -0.1, 1.1, 2, -1,
		math.NaN(), math.Inf(1), math.Inf(-1),
		math.SmallestNonzeroFloat64, math.MaxFloat64,
	} {
		f.Add(v)
	}
	f.Fuzz(func(t *testing.T, v float64) {
		err := validateRate(v, "fuzz")
		if err != nil {
			return
		}
		if math.IsNaN(v) || math.IsInf(v, 0) || v < 0 || v > 1 {
			t.Fatalf("validateRate accepted invalid %v", v)
		}
	})
}

// FuzzValidatedSignalEndpointURL: never panics; accepted URLs are http(s) with host.
func FuzzValidatedSignalEndpointURL(f *testing.F) {
	for _, s := range []string{
		"",
		"http://collector:4318",
		"https://collector:4318",
		"http://collector:4318/v1/traces",
		"grpc://c:4317",
		"file:///tmp/x",
		"http://",
		"https://user:pass@host:4318",
		"http://[::1]:4318",
		"http://host:99999",
		"http://host:0",
		"not-a-url",
	} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, endpoint string) {
		got, err := _validatedSignalEndpointURL(endpoint, "/v1/traces")
		if err != nil {
			return
		}
		u, perr := url.Parse(got)
		if perr != nil {
			t.Fatalf("accepted unparseable result %q from %q: %v", got, endpoint, perr)
		}
		if u.Scheme != "http" && u.Scheme != "https" {
			t.Fatalf("accepted non-http(s) result %q", got)
		}
		if u.Host == "" {
			t.Fatalf("accepted empty host result %q", got)
		}
	})
}

// FuzzParseEnvFloatThenValidateRate: env float path never accepts NaN/Inf/OOR.
func FuzzParseEnvFloatThenValidateRate(f *testing.F) {
	for _, s := range []string{
		"", "0", "1", "0.5", "NaN", "Inf", "-Inf", "abc", "1e9", "-0.1", "1.0001",
	} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, raw string) {
		v, err := parseEnvFloat(raw, "fuzz")
		if err != nil {
			return
		}
		if err := validateRate(v, "fuzz"); err != nil {
			return
		}
		if math.IsNaN(v) || math.IsInf(v, 0) || v < 0 || v > 1 {
			t.Fatalf("accepted invalid rate from %q → %v", raw, v)
		}
	})
}
