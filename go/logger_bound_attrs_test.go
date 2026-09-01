// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"strings"
	"testing"
)

// decodeRecord reads the single JSON record a test logger wrote.
func decodeRecord(t *testing.T, buf *bytes.Buffer) map[string]any {
	t.Helper()
	line := strings.TrimSpace(buf.String())
	if line == "" {
		t.Fatal("no record was written")
	}
	var got map[string]any
	if err := json.Unmarshal([]byte(line), &got); err != nil {
		t.Fatalf("record is not JSON (%v): %s", err, line)
	}
	return got
}

// Attributes bound once with With are sanitized on every record they appear on.
// Binding at a request boundary is the idiomatic way to carry per-request
// fields, so a credential bound there would otherwise leak on every line.
func TestLogger_With_SanitizesBoundAttributes(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = true

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "").With(slog.String("password", "hunter2"))
	l.Info("bound.attr.ok")

	out := buf.String()
	if strings.Contains(out, "hunter2") {
		t.Errorf("bound secret leaked verbatim: %s", out)
	}
	if !strings.Contains(out, "***") {
		t.Errorf("expected a redaction marker: %s", out)
	}
}

// A secret bound once is caught by secret-pattern detection too, not only by
// the key-name rules.
func TestLogger_With_DetectsSecretsInBoundValues(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = true

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "").With(slog.String("note", "AKIAIOSFODNN7EXAMPLE")) // pragma: allowlist secret
	l.Info("bound.secret.ok")

	if strings.Contains(buf.String(), "AKIAIOSFODNN7EXAMPLE") { // pragma: allowlist secret
		t.Errorf("bound secret leaked verbatim: %s", buf.String())
	}
}

// Sanitizing bound attributes must not change where they land. slog nests
// attributes under the groups open when they were bound: here `outer` sits at
// the top level, while `inner` and the record's own field sit inside "g".
func TestLogger_With_PreservesGroupNesting(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "").
		With(slog.String("outer", "a")).
		WithGroup("g").
		With(slog.String("inner", "b"))
	l.Info("group.nesting.ok", slog.String("record", "c"))

	got := decodeRecord(t, &buf)
	if got["outer"] != "a" {
		t.Errorf("outer = %v, want it at the top level", got["outer"])
	}
	group, ok := got["g"].(map[string]any)
	if !ok {
		t.Fatalf("g = %v, want a nested group", got["g"])
	}
	if group["inner"] != "b" {
		t.Errorf("g.inner = %v, want \"b\"", group["inner"])
	}
	if group["record"] != "c" {
		t.Errorf("g.record = %v, want the record's own attribute nested in g", group["record"])
	}
}

// slog elides a group that ends up with no attributes; a middleware that
// rebuilds records must elide it too rather than emitting an empty object.
func TestLogger_WithGroup_ElidesAnEmptyGroup(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	newTestLogger(&buf, cfg, "").WithGroup("empty").Info("empty.group.ok")

	if _, present := decodeRecord(t, &buf)["empty"]; present {
		t.Errorf("an empty group was emitted: %s", buf.String())
	}
}

// A group passed as a record attribute survives the processor chain with its
// contents intact. The chain converts attributes to a map and back, and a
// group whose value is not understood there is destroyed rather than rendered.
func TestLogger_GroupAttribute_SurvivesTheProcessorChain(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	newTestLogger(&buf, cfg, "").Info("group.attr.ok",
		slog.Group("g", slog.String("kept", "v"), slog.Int("n", 3)))

	got := decodeRecord(t, &buf)
	group, ok := got["g"].(map[string]any)
	if !ok {
		t.Fatalf("g = %#v, want a nested object", got["g"])
	}
	if group["kept"] != "v" {
		t.Errorf("g.kept = %v, want \"v\"", group["kept"])
	}
	if group["n"] != float64(3) {
		t.Errorf("g.n = %v, want 3", group["n"])
	}
}

// Sanitization reaches inside a group. A rule engine that cannot see into one
// leaves every nested value unredacted.
func TestLogger_GroupAttribute_IsSanitized(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = true

	var buf bytes.Buffer
	newTestLogger(&buf, cfg, "").Info("group.pii.ok",
		slog.Group("creds", slog.String("password", "hunter2")))

	if strings.Contains(buf.String(), "hunter2") {
		t.Errorf("secret inside a group leaked: %s", buf.String())
	}
}

// A required key satisfied by a bound attribute satisfies the schema. Schema
// validation and PII both read the same record, so a binding invisible to one
// is invisible to the other.
func TestLogger_With_SatisfiesRequiredKeys(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false
	cfg.EventSchema.RequiredKeys = []string{"tenant"}

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "").With(slog.String("tenant", "acme"))
	l.Info("required.key.ok")

	if strings.Contains(buf.String(), "_schema_error") {
		t.Errorf("a bound required key was not seen by schema validation: %s", buf.String())
	}
}

// slog calls WithAttrs with no attributes and WithGroup with an empty name;
// both must hand back the receiver rather than growing a step that renders
// nothing.
func TestTelemetryHandler_NoOpBindingsReturnTheReceiver(t *testing.T) {
	cfg := DefaultTelemetryConfig()
	h := _newTelemetryHandler(slog.NewJSONHandler(&bytes.Buffer{}, nil), cfg, "")

	if got := h.WithAttrs(nil); got != h {
		t.Error("WithAttrs(nil) returned a new handler")
	}
	if got := h.WithGroup(""); got != h {
		t.Error("WithGroup(\"\") returned a new handler")
	}
}

// multiHandler fans WithAttrs out to every handler it holds. The telemetry
// handler no longer delegates bindings to it, so nothing else exercises this.
func TestMultiHandler_WithAttrs_ReachesEveryHandler(t *testing.T) {
	var a, b bytes.Buffer
	mh := newMultiHandler(
		slog.NewJSONHandler(&a, nil),
		slog.NewJSONHandler(&b, nil),
	).WithAttrs([]slog.Attr{slog.String("bound", "v")})

	slog.New(mh).Info("fanout.ok")

	for name, buf := range map[string]*bytes.Buffer{"first": &a, "second": &b} {
		if !strings.Contains(buf.String(), `"bound":"v"`) {
			t.Errorf("%s handler wrote %q, want the bound attribute", name, buf.String())
		}
	}
}

// Binding nothing must leave records untouched — the common path stays on the
// original handler rather than paying for a rebuild.
func TestLogger_WithoutBindings_EmitsTheRecordUnchanged(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	newTestLogger(&buf, cfg, "").Info("plain.record.ok", slog.String("field", "v"))

	if got := decodeRecord(t, &buf); got["field"] != "v" {
		t.Errorf("field = %v, want \"v\"", got["field"])
	}
}
