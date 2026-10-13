// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"encoding/json"
	"slices"
	"strings"
	"testing"
)

// reserved_root_fields.replacement_reporting in spec/telemetry-api.yaml, and
// the contract case reserved_root_fields_replacement_reported.

func _reportingLogger(t *testing.T, cfg *TelemetryConfig) (*bytes.Buffer, func(context.Context, ...any) []map[string]any) {
	t.Helper()
	ResetForTests()
	t.Cleanup(ResetForTests)
	setupFullSampling(t)
	var buf bytes.Buffer
	logger := newTestLogger(&buf, cfg, "caller")
	return &buf, func(ctx context.Context, args ...any) []map[string]any {
		buf.Reset()
		logger.InfoContext(ctx, "reserved.fields.ok", args...)
		var records []map[string]any
		for _, line := range strings.Split(strings.TrimSpace(buf.String()), "\n") {
			var record map[string]any
			if err := json.Unmarshal([]byte(line), &record); err != nil {
				t.Fatalf("not JSON: %v: %s", err, line)
			}
			records = append(records, record)
		}
		return records
	}
}

func _warnedFields(records []map[string]any) []string {
	var fields []string
	for _, r := range records {
		if r["msg"] == _reservedWarningEvent {
			fields = append(fields, r["field"].(string))
		}
	}
	return fields
}

func _replacements() int64 { return GetHealthSnapshot().ReservedFieldReplacements }

func TestReservedReporting_AReplacedFieldIsCountedAndWarnedAboutOnce(t *testing.T) {
	_, log := _reportingLogger(t, _reservedConfig())

	first := log(context.Background(), "version", "9.9.9", "service.env", "forged")
	if got := _warnedFields(first); !slices.Equal(got, []string{"env", "version"}) {
		t.Fatalf("warned about %v, want [env version]", got)
	}
	last := first[len(first)-1]
	if last["msg"] != "reserved.fields.ok" || last["service.version"] != "1.2.3" {
		t.Fatalf("the record must follow its warnings: %v", last)
	}
	if _replacements() != 2 {
		t.Fatalf("replacements = %d, want 2", _replacements())
	}

	if got := _warnedFields(log(context.Background(), "version", "8.8.8")); len(got) != 0 {
		t.Fatalf("warned again about %v", got)
	}
	if _replacements() != 3 {
		t.Fatalf("replacements = %d, want 3", _replacements())
	}
}

func TestReservedReporting_TheWarningNamesTheFieldNotTheValue(t *testing.T) {
	_, log := _reportingLogger(t, _reservedConfig())
	records := log(context.Background(), "service.version", "secret-build-7")
	warning := records[0]
	if warning["msg"] != _reservedWarningEvent || warning["field"] != "version" || warning["level"] != "WARN" {
		t.Fatalf("unexpected warning: %v", warning)
	}
	if warning["logger_name"] != _reservedWarningLogger {
		t.Fatalf("logger_name = %v, want %q", warning["logger_name"], _reservedWarningLogger)
	}
	raw, _ := json.Marshal(warning)
	if strings.Contains(string(raw), "secret-build-7") {
		t.Fatalf("the warning carries the caller's value: %s", raw)
	}
}

func TestReservedReporting_AnEqualValueIsNotAReplacement(t *testing.T) {
	_, log := _reportingLogger(t, _reservedConfig())
	if got := _warnedFields(log(context.Background(), "version", "1.2.3", "service.name", "real-svc")); len(got) != 0 {
		t.Fatalf("warned about %v", got)
	}
	if _replacements() != 0 {
		t.Fatalf("replacements = %d, want 0", _replacements())
	}
}

func TestReservedReporting_AnEmptyConfigValueReplacesNothing(t *testing.T) {
	cfg := _reservedConfig()
	cfg.Version = ""
	_, log := _reportingLogger(t, cfg)
	log(context.Background(), "version", "9.9.9")
	if _replacements() != 0 {
		t.Fatalf("replacements = %d, want 0", _replacements())
	}
}

func TestReservedReporting_TraceIDsCountOnlyWhileASpanIsLive(t *testing.T) {
	_, log := _reportingLogger(t, _reservedConfig())
	log(context.Background(), "trace_id", "caller-trace")
	if _replacements() != 0 {
		t.Fatalf("replacements = %d with no span, want 0", _replacements())
	}

	ctx := SetTraceContext(context.Background(), "real-trace", "real-span")
	got := _warnedFields(log(ctx, "trace.id", "fake-trace", "span_id", "fake-span"))
	if !slices.Equal(got, []string{"trace_id", "span_id"}) {
		t.Fatalf("warned about %v, want [trace_id span_id]", got)
	}
	log(ctx, "trace.id", "real-trace")
	if _replacements() != 2 {
		t.Fatalf("replacements = %d, want 2", _replacements())
	}
}

func TestReservedReporting_ABoundValueCountsOnceAndNotForItsWarning(t *testing.T) {
	ResetForTests()
	t.Cleanup(ResetForTests)
	setupFullSampling(t)
	var buf bytes.Buffer
	newTestLogger(&buf, _reservedConfig(), "caller").With("version", "bound").Info("reserved.fields.ok")
	if !strings.Contains(buf.String(), _reservedWarningEvent) {
		t.Fatalf("no warning: %s", buf.String())
	}
	// The warning runs the same stamping; it must not count the bound value
	// a second time.
	if _replacements() != 1 {
		t.Fatalf("replacements = %d, want 1", _replacements())
	}
}

func TestReservedReporting_ARefusedRecordIsNeitherCountedNorWarnedAbout(t *testing.T) {
	ResetForTests()
	t.Cleanup(ResetForTests)
	var buf bytes.Buffer
	if _, err := SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0}); err != nil {
		t.Fatal(err)
	}
	newTestLogger(&buf, _reservedConfig(), "caller").Info("reserved.fields.ok", "version", "9.9.9")
	if buf.Len() != 0 || _replacements() != 0 {
		t.Fatalf("refused record reported: %d replacements, output %q", _replacements(), buf.String())
	}
}

func TestReservedReporting_ResetClearsTheWarnedSet(t *testing.T) {
	_, log := _reportingLogger(t, _reservedConfig())
	log(context.Background(), "version", "9.9.9")
	_resetReservedWarnings()
	if got := _warnedFields(log(context.Background(), "version", "9.9.9")); !slices.Equal(got, []string{"version"}) {
		t.Fatalf("warned about %v after reset, want [version]", got)
	}
}
