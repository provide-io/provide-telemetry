// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

type panickingError struct{}

func (panickingError) Error() string { panic("Error() exploded") }

type panickingText struct{}

func (panickingText) MarshalText() ([]byte, error) { panic("MarshalText() exploded") }

// nilFieldError panics the realistic way: Error() dereferences a field the
// caller never set.
type nilFieldError struct{ inner *struct{ msg string } }

func (e *nilFieldError) Error() string { return e.inner.msg }

type workingText struct{}

func (workingText) MarshalText() ([]byte, error) { return []byte("as-text"), nil }

func TestHardenRecoversPanickingSelfDescription(t *testing.T) {
	limits := DefaultLimits()
	cases := []struct {
		name  string
		input any
		want  any
	}{
		{"panicking Error is redacted", panickingError{}, Redacted},
		{"panicking MarshalText is redacted", panickingText{}, Redacted},
		{"nil dereference behind a pointer receiver is redacted", &nilFieldError{}, Redacted},
		// The guard does not swallow the working cases.
		{"working MarshalText still renders", workingText{}, "as-text"},
		{"panic in one value leaves its siblings intact",
			map[string]any{"bad": panickingError{}, "good": "kept"},
			map[string]any{"bad": Redacted, "good": "kept"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := Harden(tc.input, limits); !reflect.DeepEqual(tc.want, got) {
				t.Errorf("got %#v, want %#v", got, tc.want)
			}
		})
	}
}

// The end-to-end property: a log call carrying a value whose Error() panics
// still emits its record, with only that value replaced.
func TestLogRecordSurvivesPanickingAttribute(t *testing.T) {
	setupFullSampling(t)
	cfg := DefaultTelemetryConfig()
	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")

	l.InfoContext(context.Background(), "panic.attr.check", "err", panickingError{}, "other", "value")

	line := strings.TrimSpace(buf.String())
	var decoded map[string]any
	if err := json.Unmarshal([]byte(line), &decoded); err != nil {
		t.Fatalf("no record emitted: %v: %q", err, line)
	}
	if decoded["err"] != Redacted {
		t.Fatalf("err = %v, want %q", decoded["err"], Redacted)
	}
	if decoded["other"] != "value" {
		t.Fatalf("sibling attribute lost: %v", decoded)
	}
}
