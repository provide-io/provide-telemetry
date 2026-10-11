// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"
)

// _reservedRecord logs one record and returns the raw JSON line alongside its
// decoded form. The raw line is what catches a duplicate key: decoding into a
// map keeps only one of the two.
func _reservedRecord(t *testing.T, cfg *TelemetryConfig, ctx context.Context, args ...any) (string, map[string]any) {
	t.Helper()
	setupFullSampling(t)
	var buf bytes.Buffer
	newTestLogger(&buf, cfg, "").InfoContext(ctx, "reserved.fields.check", args...)
	line := strings.TrimSpace(buf.String())
	var decoded map[string]any
	if err := json.Unmarshal([]byte(line), &decoded); err != nil {
		t.Fatalf("record is not JSON: %v: %s", err, line)
	}
	return line, decoded
}

func _assertSingleField(t *testing.T, line string, decoded map[string]any, key, want string) {
	t.Helper()
	if n := strings.Count(line, `"`+key+`":`); n != 1 {
		t.Fatalf("%s appears %d times, want 1: %s", key, n, line)
	}
	if decoded[key] != want {
		t.Fatalf("%s = %v, want %q: %s", key, decoded[key], want, line)
	}
}

func _reservedConfig() *TelemetryConfig {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false
	cfg.ServiceName = "real-svc"
	cfg.Environment = "real-env"
	cfg.Version = "1.2.3"
	return cfg
}

func TestReservedFields_LiveTraceContextReplacesCallerValues(t *testing.T) {
	ctx := SetTraceContext(context.Background(), "real-trace", "real-span")
	line, decoded := _reservedRecord(t, _reservedConfig(), ctx,
		"trace.id", "fake-trace", "span.id", "fake-span", "keep", "me")

	_assertSingleField(t, line, decoded, "trace.id", "real-trace")
	_assertSingleField(t, line, decoded, "span.id", "real-span")
	_assertSingleField(t, line, decoded, "keep", "me")
	if strings.Contains(line, "fake-") {
		t.Fatalf("caller's forged value survived: %s", line)
	}
}

func TestReservedFields_ConfiguredIdentityReplacesCallerValues(t *testing.T) {
	line, decoded := _reservedRecord(t, _reservedConfig(), context.Background(),
		"service.name", "fake-svc", "service.env", "fake-env", "service.version", "9.9.9")

	_assertSingleField(t, line, decoded, "service.name", "real-svc")
	_assertSingleField(t, line, decoded, "service.env", "real-env")
	_assertSingleField(t, line, decoded, "service.version", "1.2.3")
}

// With no live trace context nothing better than the caller's value is known,
// so it stands — the rule Python, TypeScript and Rust follow too.
func TestReservedFields_CallerValueStandsWhenNothingIsStamped(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false
	cfg.ServiceName = ""
	cfg.Environment = ""
	cfg.Version = ""
	line, decoded := _reservedRecord(t, cfg, context.Background(),
		"trace.id", "caller-trace", "service.name", "caller-svc")

	_assertSingleField(t, line, decoded, "trace.id", "caller-trace")
	_assertSingleField(t, line, decoded, "service.name", "caller-svc")
}

// Each field is replaced only when the library stamps that field: a context
// with a trace ID but no span ID leaves the caller's span.id alone, and an
// unset Version leaves the caller's service.version alone.
func TestReservedFields_OnlyStampedKeysAreReplaced(t *testing.T) {
	cfg := _reservedConfig()
	cfg.Version = ""
	ctx := SetTraceContext(context.Background(), "real-trace", "")
	line, decoded := _reservedRecord(t, cfg, ctx,
		"trace.id", "fake-trace", "span.id", "caller-span", "service.version", "caller-ver")

	_assertSingleField(t, line, decoded, "trace.id", "real-trace")
	_assertSingleField(t, line, decoded, "span.id", "caller-span")
	_assertSingleField(t, line, decoded, "service.version", "caller-ver")
	_assertSingleField(t, line, decoded, "service.name", "real-svc")
}

// Bound attributes and context-bound fields reach the root just like call-site
// attributes, so they are replaced the same way.
func TestReservedFields_BoundAndContextFieldsAreReplaced(t *testing.T) {
	setupFullSampling(t)
	var buf bytes.Buffer
	l := newTestLogger(&buf, _reservedConfig(), "").With("trace.id", "bound-trace")
	ctx := BindContext(context.Background(), map[string]any{"span.id": "ctx-span", "service.name": "ctx-svc"})
	ctx = SetTraceContext(ctx, "real-trace", "real-span")
	l.InfoContext(ctx, "reserved.fields.bound")

	line := strings.TrimSpace(buf.String())
	var decoded map[string]any
	if err := json.Unmarshal([]byte(line), &decoded); err != nil {
		t.Fatal(err)
	}
	_assertSingleField(t, line, decoded, "trace.id", "real-trace")
	_assertSingleField(t, line, decoded, "span.id", "real-span")
	_assertSingleField(t, line, decoded, "service.name", "real-svc")
}

// A reserved name inside a group is a different field and the caller's to use.
func TestReservedFields_GroupedKeysAreLeftAlone(t *testing.T) {
	ctx := SetTraceContext(context.Background(), "real-trace", "real-span")
	_, decoded := _reservedRecord(t, _reservedConfig(), ctx,
		"upstream", map[string]any{"trace.id": "their-trace"})

	upstream, ok := decoded["upstream"].(map[string]any)
	if !ok || upstream["trace.id"] != "their-trace" {
		t.Fatalf("grouped trace.id was touched: %v", decoded["upstream"])
	}
	if decoded["trace.id"] != "real-trace" {
		t.Fatalf("root trace.id = %v", decoded["trace.id"])
	}
}
