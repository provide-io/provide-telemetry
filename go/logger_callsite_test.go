// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"bytes"
	"context"
	"fmt"
	"log/slog"
	"runtime"
	"strings"
	"testing"
	"time"
)

// _thisFile is the base name every assertion here expects to see reported as the
// callsite. Written as a literal rather than derived from runtime.Caller so a
// helper accidentally becoming the reported frame is a failure, not a tautology.
const _thisFile = "logger_callsite_test.go"

// callsiteLogger installs a JSON logger writing to buf with the two callsite
// knobs set from the environment, the way a host configures them.
func callsiteLogger(t *testing.T, buf *bytes.Buffer, includeCaller, codeAttributes string) *slog.Logger {
	t.Helper()
	return callsiteLoggerFormat(t, buf, LogFormatJSON, includeCaller, codeAttributes)
}

func callsiteLoggerFormat(t *testing.T, buf *bytes.Buffer, format, includeCaller, codeAttributes string) *slog.Logger {
	t.Helper()
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })
	t.Setenv("PROVIDE_LOG_FORMAT", format)
	t.Setenv("PROVIDE_LOG_INCLUDE_CALLER", includeCaller)
	t.Setenv("PROVIDE_LOG_CODE_ATTRIBUTES", codeAttributes)

	if _, err := SetupTelemetry(WithLogOutput(buf)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	return GetLogger(context.Background(), "callsite.test")
}

// PROVIDE_LOG_INCLUDE_CALLER puts the caller's file and line on the record.
func TestCallsite_IncludeCallerAddsFilenameAndLineno(t *testing.T) {
	var buf bytes.Buffer
	logger := callsiteLogger(t, &buf, "true", "false")

	_, _, line, _ := runtime.Caller(0)
	logger.Info("callsite-include")

	rec := decodeRecord(t, &buf)
	if rec["filename"] != _thisFile {
		t.Errorf("filename is %v, want %q", rec["filename"], _thisFile)
	}
	want := float64(line + 1)
	if rec["lineno"] != want {
		t.Errorf("lineno is %v, want %v (the caller's line, not the SDK's)", rec["lineno"], want)
	}
}

// filename is a base name. An absolute path would leak the build machine's
// directory layout into every record.
func TestCallsite_FilenameIsBaseNameNotAPath(t *testing.T) {
	var buf bytes.Buffer
	callsiteLogger(t, &buf, "true", "false").Info("callsite-basename")

	name, ok := decodeRecord(t, &buf)["filename"].(string)
	if !ok {
		t.Fatalf("filename missing from the record")
	}
	if strings.ContainsAny(name, `/\`) {
		t.Errorf("filename is %q, want a bare base name", name)
	}
}

// The knob off means neither field appears.
func TestCallsite_DisabledOmitsBothFields(t *testing.T) {
	var buf bytes.Buffer
	callsiteLogger(t, &buf, "false", "false").Info("callsite-off")

	rec := decodeRecord(t, &buf)
	for _, key := range []string{"filename", "lineno"} {
		if _, present := rec[key]; present {
			t.Errorf("%s is present with PROVIDE_LOG_INCLUDE_CALLER=false", key)
		}
	}
}

// PROVIDE_LOG_CODE_ATTRIBUTES emits the current-semconv code attributes and does
// NOT require PROVIDE_LOG_INCLUDE_CALLER: the two knobs select different outputs
// from one capture.
func TestCallsite_CodeAttributesAreIndependentOfIncludeCaller(t *testing.T) {
	var buf bytes.Buffer
	logger := callsiteLogger(t, &buf, "false", "true")

	_, file, line, _ := runtime.Caller(0)
	logger.Info("callsite-code-attrs")

	rec := decodeRecord(t, &buf)
	if rec["code.file.path"] != file {
		t.Errorf("code.file.path is %v, want %q", rec["code.file.path"], file)
	}
	if want := float64(line + 1); rec["code.line.number"] != want {
		t.Errorf("code.line.number is %v, want %v", rec["code.line.number"], want)
	}
	fn, _ := rec["code.function.name"].(string)
	if !strings.HasSuffix(fn, "TestCallsite_CodeAttributesAreIndependentOfIncludeCaller") {
		t.Errorf("code.function.name is %q, want the calling function", fn)
	}
	for _, key := range []string{"filename", "lineno"} {
		if _, present := rec[key]; present {
			t.Errorf("%s leaked in with PROVIDE_LOG_INCLUDE_CALLER=false", key)
		}
	}
}

// The deprecated semconv spellings are never emitted.
func TestCallsite_DeprecatedCodeAttributeNamesAreNotEmitted(t *testing.T) {
	var buf bytes.Buffer
	callsiteLogger(t, &buf, "true", "true").Info("callsite-semconv")

	rec := decodeRecord(t, &buf)
	for _, key := range []string{"code.filepath", "code.lineno", "code.namespace"} {
		if _, present := rec[key]; present {
			t.Errorf("%s is emitted; only the current semconv names are canonical", key)
		}
	}
}

// Both knobs on yields all five fields.
func TestCallsite_BothKnobsEmitBothShapes(t *testing.T) {
	var buf bytes.Buffer
	callsiteLogger(t, &buf, "true", "true").Info("callsite-both")

	rec := decodeRecord(t, &buf)
	for _, key := range []string{"filename", "lineno", "code.file.path", "code.function.name", "code.line.number"} {
		if _, present := rec[key]; !present {
			t.Errorf("%s missing when both knobs are enabled", key)
		}
	}
}

// Code attributes off means none of them appear even with the caller knob on.
func TestCallsite_CodeAttributesDisabledOmitsThem(t *testing.T) {
	var buf bytes.Buffer
	callsiteLogger(t, &buf, "true", "false").Info("callsite-no-code")

	rec := decodeRecord(t, &buf)
	for _, key := range []string{"code.file.path", "code.function.name", "code.line.number"} {
		if _, present := rec[key]; present {
			t.Errorf("%s is present with PROVIDE_LOG_CODE_ATTRIBUTES=false", key)
		}
	}
}

// All three renderers report the callsite. The pretty renderer takes no
// slog.HandlerOptions, so a HandlerOptions-only implementation would silently
// skip it.
func TestCallsite_EveryRendererReportsTheCallsite(t *testing.T) {
	renderers := []struct {
		format    string
		lineToken string // how that renderer spells the lineno pair
	}{
		{LogFormatJSON, `"lineno":%d`},
		{LogFormatConsole, "lineno=%d"},
		{LogFormatPretty, "lineno=%d"},
	}
	for _, renderer := range renderers {
		t.Run(renderer.format, func(t *testing.T) {
			var buf bytes.Buffer
			logger := callsiteLoggerFormat(t, &buf, renderer.format, "true", "false")

			_, _, line, _ := runtime.Caller(0)
			logger.Info("callsite-renderer")

			out := buf.String()
			if !strings.Contains(out, _thisFile) {
				t.Errorf("%s output %q omits the caller's filename", renderer.format, out)
			}
			want := fmt.Sprintf(renderer.lineToken, line+1)
			if !strings.Contains(out, want) {
				t.Errorf("%s output %q omits %s", renderer.format, out, want)
			}
		})
	}
}

// The callsite is the only source of these keys. applyCallsite is the one
// processor that runs after applyPII, which is where every earlier step's
// duplicate keys get collapsed by the map round trip — so without shadowing
// here, a caller logging its own "filename" would produce a record carrying the
// key twice. Python assigns into the event dict, so the callsite wins; this
// matches that.
func TestCallsite_ShadowsCallerSuppliedFieldsOfTheSameName(t *testing.T) {
	var buf bytes.Buffer
	logger := callsiteLogger(t, &buf, "true", "true")

	logger.Info("callsite-shadow",
		"filename", "uploaded-by-the-user.csv",
		"lineno", 4242,
		"code.file.path", "/somewhere/else.go",
	)

	line := strings.TrimSpace(buf.String())
	for _, key := range []string{`"filename"`, `"lineno"`, `"code.file.path"`} {
		if n := strings.Count(line, key); n != 1 {
			t.Errorf("%s appears %d times in %s, want exactly 1", key, n, line)
		}
	}
	rec := decodeRecord(t, &buf)
	if rec["filename"] != _thisFile {
		t.Errorf("filename is %v, want the callsite's %q", rec["filename"], _thisFile)
	}
	if rec["lineno"] == float64(4242) {
		t.Error("lineno is the caller-supplied value, want the callsite's line")
	}
}

// PROVIDE_LOG_CODE_ATTRIBUTES exists for OTel log records, so the attributes
// have to reach the backend bridge — which sits below the telemetry handler,
// under multiHandler, and never sees slog.HandlerOptions.
func TestCallsite_CodeAttributesReachTheBackendBridge(t *testing.T) {
	resetSetupState(t)
	t.Cleanup(func() { resetSetupState(t) })

	backend := &_fakeBackend{}
	RegisterBackend("callsite-bridge", backend)
	// Unregistered, not merely reset: RegisterBackend makes the named backend
	// the active one, and _resetSetup only calls ResetForTests on the registry
	// without emptying it. A backend left active here would still be bridged to
	// from every later test, including the concurrent one, whose goroutines
	// would then all append to this fake's unsynchronized slices.
	t.Cleanup(func() { UnregisterBackend("callsite-bridge") })

	t.Setenv("PROVIDE_LOG_CODE_ATTRIBUTES", "true")
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
	if _, err := SetupTelemetry(); err != nil {
		t.Fatalf("setup failed: %v", err)
	}

	_, file, line, _ := runtime.Caller(0)
	GetLogger(context.Background(), "callsite.bridge").Info("callsite-bridged")

	if len(backend.logAttrs) != 1 {
		t.Fatalf("expected 1 bridged record, got %d", len(backend.logAttrs))
	}
	bridged := backend.logAttrs[0]
	if bridged[_attrCodeFilePath] != file {
		t.Errorf("bridged code.file.path is %v, want %q", bridged[_attrCodeFilePath], file)
	}
	if bridged[_attrCodeLineNumber] != int64(line+1) {
		t.Errorf("bridged code.line.number is %#v, want %d", bridged[_attrCodeLineNumber], line+1)
	}
	if _, present := bridged[_attrCodeFunctionName]; !present {
		t.Error("bridged record carries no code.function.name")
	}
}

// A record built without a PC — the shape any handler-level caller can hand in —
// carries no callsite, rather than filename "" and lineno 0.
func TestCallsite_RecordWithoutAPCEmitsNothing(t *testing.T) {
	rec := handleSyntheticRecord(t, 0)
	for _, key := range []string{"filename", "lineno", "code.file.path"} {
		if _, present := rec[key]; present {
			t.Errorf("%s emitted for a record with no PC", key)
		}
	}
}

// A PC the runtime cannot resolve is treated the same way.
func TestCallsite_UnresolvablePCEmitsNothing(t *testing.T) {
	rec := handleSyntheticRecord(t, 1)
	for _, key := range []string{"filename", "lineno", "code.file.path"} {
		if _, present := rec[key]; present {
			t.Errorf("%s emitted for an unresolvable PC", key)
		}
	}
}

// handleSyntheticRecord pushes a hand-built record carrying pc through the
// telemetry handler chain and returns the rendered JSON.
func handleSyntheticRecord(t *testing.T, pc uintptr) map[string]any {
	t.Helper()
	var buf bytes.Buffer
	callsiteLogger(t, &buf, "true", "true")

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Format = LogFormatJSON
	cfg.Logging.LogCodeAttributes = true
	handler := _newTelemetryHandler(_baseLogHandler(cfg), cfg, "callsite.test")
	record := slog.NewRecord(time.Now(), slog.LevelInfo, "callsite-synthetic", pc)
	if err := handler.Handle(context.Background(), record); err != nil {
		t.Fatalf("handle failed: %v", err)
	}
	return decodeRecord(t, &buf)
}

// _callsiteBaseName trims every directory component, on either separator, and
// leaves a bare name alone.
func TestCallsiteBaseName(t *testing.T) {
	cases := map[string]string{
		"/home/build/src/app/main.go":  "main.go",
		`C:\build\src\app\main.go`:     "main.go",
		"main.go":                      "main.go",
		"/home/build/src/app/":         "",
		"github.com/x/y@v1.2.3/pkg.go": "pkg.go",
	}
	for in, want := range cases {
		if got := _callsiteBaseName(in); got != want {
			t.Errorf("_callsiteBaseName(%q) = %q, want %q", in, got, want)
		}
	}
}
