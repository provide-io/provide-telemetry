// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

import (
	"context"
	"reflect"
	"testing"
)

type bridgeRow struct {
	Password string `json:"password"`
	Public   string `json:"public"`
}

// TestBackendBridgeReceivesHardenedRedactedRecords is the end of the leak this
// task closes, and it takes two fixes to pass.
//
// The bridge used to be a *sibling* of the telemetry handler rather than a
// handler downstream of it, so every record exported to a backend arrived
// exactly as the caller wrote it — no consent gate, no schema check, no
// sampling, no hardening and no redaction. And even on the local side, a
// []bridgeRow was invisible to the PII engine, which walked only map[string]any
// and []any. A password masked in the local log therefore left the process in
// the clear.
func TestBackendBridgeReceivesHardenedRedactedRecords(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_fakeBackend{}
	previous, replaced := RegisterBackend("bridge-hardening", backend)
	t.Cleanup(func() {
		if replaced {
			RegisterBackend("bridge-hardening", previous)
		}
	})

	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	GetLogger(context.Background(), "bridge.logger").Info(
		"export", "rows", []bridgeRow{{Password: "s3cr3t", Public: "ok"}})

	if len(backend.logAttrs) != 1 {
		t.Fatalf("expected 1 bridged record, got %d", len(backend.logAttrs))
	}
	rows, ok := backend.logAttrs[0]["rows"].([]any)
	if !ok || len(rows) != 1 {
		t.Fatalf("typed slice never became traversable: %#v", backend.logAttrs[0]["rows"])
	}
	want := map[string]any{"password": Redacted, "public": "ok"}
	if !reflect.DeepEqual(want, rows[0]) {
		t.Fatalf("bridged row: got %#v, want %#v", rows[0], want)
	}
}
