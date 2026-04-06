// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry_test

import (
	"strings"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
)

func TestRedactedStringMasksLoggingOTLPHeaders(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{}
	cfg.Logging.OTLPHeaders = map[string]string{"Authorization": "Bearer super-secret-token"}
	s := cfg.String()
	if strings.Contains(s, "super-secret-token") {
		t.Errorf("String() leaked header value: %s", s)
	}
	if !strings.Contains(s, "****") {
		t.Errorf("String() missing mask: %s", s)
	}
}

func TestRedactedStringMasksTracingOTLPHeaders(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{}
	cfg.Tracing.OTLPHeaders = map[string]string{"X-Api-Key": "sk-1234567890abcdef"} // pragma: allowlist secret
	s := cfg.String()
	if strings.Contains(s, "1234567890abcdef") { // pragma: allowlist secret
		t.Errorf("String() leaked header value: %s", s)
	}
	if !strings.Contains(s, "****") {
		t.Errorf("String() missing mask: %s", s)
	}
}

func TestRedactedStringMasksEndpointCredentials(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{}
	cfg.Tracing.OTLPEndpoint = "https://user:p4ssw0rd@otel.example.com/v1/traces" // pragma: allowlist secret
	s := cfg.String()
	if strings.Contains(s, "p4ssw0rd") {
		t.Errorf("String() leaked password: %s", s)
	}
	if !strings.Contains(s, "****") {
		t.Errorf("String() missing mask: %s", s)
	}
}

func TestRedactedStringMasksMetricsEndpointCredentials(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{}
	cfg.Metrics.OTLPEndpoint = "https://user:s3cret99@metrics.example.com/v1/metrics" // pragma: allowlist secret
	s := cfg.String()
	if strings.Contains(s, "s3cret99") {
		t.Errorf("String() leaked metrics password: %s", s)
	}
	if !strings.Contains(s, "****") {
		t.Errorf("String() missing mask: %s", s)
	}
}

func TestRedactedStringSafeWithNoSecrets(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{ServiceName: "my-service"}
	s := cfg.String()
	if !strings.Contains(s, "my-service") {
		t.Errorf("String() missing service name: %s", s)
	}
}

func TestShortHeaderValueFullyMasked(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{}
	cfg.Logging.OTLPHeaders = map[string]string{"X-Key": "short"}
	s := cfg.String()
	if strings.Contains(s, "short") {
		t.Errorf("String() leaked short value: %s", s)
	}
	if !strings.Contains(s, "****") {
		t.Errorf("String() missing mask: %s", s)
	}
}

func TestGoStringAlsoRedacts(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{}
	cfg.Logging.OTLPHeaders = map[string]string{"Authorization": "Bearer supersecretvalue"}
	s := cfg.GoString()
	if strings.Contains(s, "supersecretvalue") {
		t.Errorf("GoString() leaked header value: %s", s)
	}
}

func TestRedactedStringMethod(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{ServiceName: "svc"}
	s := cfg.RedactedString()
	if !strings.Contains(s, "svc") {
		t.Errorf("RedactedString() missing service name: %s", s)
	}
}

func TestEndpointWithNoPassword(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{}
	cfg.Tracing.OTLPEndpoint = "https://otel.example.com/v1/traces"
	s := cfg.String()
	if !strings.Contains(s, "otel.example.com") {
		t.Errorf("String() stripped non-secret endpoint: %s", s)
	}
}

func TestMaskHeaderValueLongViaString(t *testing.T) {
	cfg := &telemetry.TelemetryConfig{}
	cfg.Logging.OTLPHeaders = map[string]string{"Authorization": "Bearer super-secret-token"}
	s := cfg.String()
	// "Bear****" should appear — first 4 chars of "Bearer super-secret-token"
	if !strings.Contains(s, "Bear****") {
		t.Errorf("expected Bear**** in masked output, got: %s", s)
	}
}

func TestEndpointWithUsernameNoPassword(t *testing.T) {
	// URL with username but no password — hasPass is false → maskEndpointURL returns raw.
	cfg := &telemetry.TelemetryConfig{}
	cfg.Tracing.OTLPEndpoint = "https://user@otel.example.com/v1/traces"
	s := cfg.String()
	if !strings.Contains(s, "otel.example.com") {
		t.Errorf("String() stripped non-secret endpoint: %s", s)
	}
}

func TestEndpointWithPasswordAndPort(t *testing.T) {
	// URL with password AND explicit port — exercises the port branch in maskEndpointURL.
	cfg := &telemetry.TelemetryConfig{}
	cfg.Tracing.OTLPEndpoint = "https://user:s3cr3t@otel.example.com:4318/v1/traces" // pragma: allowlist secret
	s := cfg.String()
	if strings.Contains(s, "s3cr3t") {
		t.Errorf("String() leaked password in port URL: %s", s)
	}
	if !strings.Contains(s, "4318") {
		t.Errorf("String() dropped port from masked URL: %s", s)
	}
}
