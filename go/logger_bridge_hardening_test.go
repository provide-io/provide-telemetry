// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

package telemetry

import (
	"context"
	"log/slog"
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

// TestDefaultLoggerBridgeReceivesHardenedRedactedRecords is the sibling of the
// GetLogger test above for the package-level Logger()/slog.Default() path.
// _wireBackendBindingsLocked used to wire the bridge as a sibling of the
// telemetry handler — newMultiHandler(Logger().Handler(), bridge) — so records
// logged through slog.Default() were handed to the backend raw: no consent, no
// module log level, no sampling, no backpressure, no hardening, no PII
// redaction. The console line showed password="***" while the plaintext secret
// left for the OTLP collector.
func TestDefaultLoggerBridgeReceivesHardenedRedactedRecords(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_fakeBackend{}
	previous, replaced := RegisterBackend("default-bridge-hardening", backend)
	t.Cleanup(func() {
		if replaced {
			RegisterBackend("default-bridge-hardening", previous)
		} else {
			UnregisterBackend("default-bridge-hardening")
		}
	})

	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	// A record the policy chain suppresses (default level is INFO) must never
	// reach the bridge. The bridge's own Enabled() always answers true, so as
	// a sibling it exported exactly these records.
	slog.Debug("suppressed", "password", "s3cr3t")
	if len(backend.logAttrs) != 0 {
		t.Fatalf("a level-suppressed record reached the bridge: %#v", backend.logAttrs)
	}

	slog.Info("export", "password", "s3cr3t", "public", "ok")
	if len(backend.logAttrs) != 1 {
		t.Fatalf("expected 1 bridged record, got %d", len(backend.logAttrs))
	}
	got := backend.logAttrs[0]
	if got["password"] != Redacted {
		t.Fatalf("the bridge saw the plaintext secret: %#v", got["password"])
	}
	if got["public"] != "ok" {
		t.Fatalf("public value was altered: %#v", got["public"])
	}
}
