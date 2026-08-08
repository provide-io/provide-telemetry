// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package otel

import (
	"strings"
	"testing"

	telemetry "github.com/provide-io/provide-telemetry/go"
	"go.opentelemetry.io/otel/attribute"
)

// TestSpanAttributeMapsHardenedValues pins how a hardened value lands on a span.
// Span attributes never pass through the logger's handler chain, so this and
// the Harden call in SetAttribute are the whole of their bounding.
func TestSpanAttributeMapsHardenedValues(t *testing.T) {
	cases := []struct {
		name  string
		input any
		want  attribute.Value
	}{
		{"bool", true, attribute.BoolValue(true)},
		{"int widens to int64", 7, attribute.Int64Value(7)},
		{"float", 1.25, attribute.Float64Value(1.25)},
		{"string", "alpha", attribute.StringValue("alpha")},
		{"control characters are stripped", "a\x00b", attribute.StringValue("ab")},
		{"nil", nil, attribute.StringValue("null")},
		{"unsigned", uint8(9), attribute.StringValue("9")},
		{"struct travels as canonical JSON", struct {
			Field string `json:"field"`
		}{Field: "value"}, attribute.StringValue(`{"field":"value"}`)},
		{"channel has no shape", make(chan int), attribute.StringValue("***")},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			kv := _spanAttribute("k", telemetry.Harden(tc.input, telemetry.DefaultLimits()))
			if kv.Key != "k" {
				t.Errorf("key: got %q", kv.Key)
			}
			if kv.Value != tc.want {
				t.Errorf("value: got %v, want %v", kv.Value, tc.want)
			}
		})
	}
}

// TestSpanAttributeTruncatesUnboundedStrings pins the cap. An exporter that
// receives a megabyte attribute has no way to refuse it.
func TestSpanAttributeTruncatesUnboundedStrings(t *testing.T) {
	long := strings.Repeat("x", 4096)
	kv := _spanAttribute("k", telemetry.Harden(long, telemetry.DefaultLimits()))
	got := kv.Value.AsString()
	if len(got) >= len(long) {
		t.Fatalf("attribute was not truncated: %d chars", len(got))
	}
	if !strings.HasSuffix(got, "...") {
		t.Errorf("truncated value lost its marker: %q", got[len(got)-8:])
	}
}
