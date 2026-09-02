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
	backend, logger := callsiteBridgeLogger(t, &buf, "false", "true")

	_, file, line, _ := runtime.Caller(0)
	logger.Info("callsite-code-attrs")

	bridged := bridgedRecord(t, backend)
	if bridged[_attrCodeFilePath] != file {
		t.Errorf("code.file.path is %v, want %q", bridged[_attrCodeFilePath], file)
	}
	if bridged[_attrCodeLineNumber] != int64(line+1) {
		t.Errorf("code.line.number is %#v, want %d", bridged[_attrCodeLineNumber], line+1)
	}
	fn, _ := bridged[_attrCodeFunctionName].(string)
	if !strings.HasSuffix(fn, "TestCallsite_CodeAttributesAreIndependentOfIncludeCaller") {
		t.Errorf("code.function.name is %q, want the calling function", fn)
	}
	for _, key := range []string{"filename", "lineno"} {
		if _, present := bridged[key]; present {
			t.Errorf("%s leaked in with PROVIDE_LOG_INCLUDE_CALLER=false", key)
		}
	}
}

// The deprecated semconv spellings are never emitted.
func TestCallsite_DeprecatedCodeAttributeNamesAreNotEmitted(t *testing.T) {
	var buf bytes.Buffer
	backend, logger := callsiteBridgeLogger(t, &buf, "true", "true")
	logger.Info("callsite-semconv")

	bridged := bridgedRecord(t, backend)
	for _, key := range []string{"code.filepath", "code.lineno", "code.namespace"} {
		if _, present := bridged[key]; present {
			t.Errorf("%s is emitted; only the current semconv names are canonical", key)
		}
	}
}

// Both knobs on yields all five fields, split across the two audiences.
func TestCallsite_BothKnobsEmitBothShapes(t *testing.T) {
	var buf bytes.Buffer
	backend, logger := callsiteBridgeLogger(t, &buf, "true", "true")
	logger.Info("callsite-both")

	bridged := bridgedRecord(t, backend)
	for _, key := range []string{"filename", "lineno", _attrCodeFilePath, _attrCodeFunctionName, _attrCodeLineNumber} {
		if _, present := bridged[key]; !present {
			t.Errorf("%s missing from the exported record when both knobs are enabled", key)
		}
	}
	rec := decodeRecord(t, &buf)
	for _, key := range []string{"filename", "lineno"} {
		if _, present := rec[key]; !present {
			t.Errorf("%s missing from the rendered record when both knobs are enabled", key)
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
	)

	line := strings.TrimSpace(buf.String())
	for _, key := range []string{`"filename"`, `"lineno"`} {
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

// callsiteBridgeLogger installs a JSON logger writing to buf *and* a fake
// backend, so one emitted record can be inspected on both surfaces: what the
// host sees rendered, and what leaves for the collector.
func callsiteBridgeLogger(t *testing.T, buf *bytes.Buffer, includeCaller, codeAttributes string) (*_fakeBackend, *slog.Logger) {
	t.Helper()
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

	t.Setenv("PROVIDE_LOG_FORMAT", LogFormatJSON)
	t.Setenv("PROVIDE_LOG_INCLUDE_CALLER", includeCaller)
	t.Setenv("PROVIDE_LOG_CODE_ATTRIBUTES", codeAttributes)
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
	if _, err := SetupTelemetry(WithLogOutput(buf)); err != nil {
		t.Fatalf("setup failed: %v", err)
	}
	return backend, GetLogger(context.Background(), "callsite.bridge")
}

// bridgedRecord returns the single record the fake backend received.
func bridgedRecord(t *testing.T, backend *_fakeBackend) map[string]any {
	t.Helper()
	if len(backend.logAttrs) != 1 {
		t.Fatalf("expected 1 bridged record, got %d", len(backend.logAttrs))
	}
	return backend.logAttrs[0]
}

// PROVIDE_LOG_CODE_ATTRIBUTES exists for OTel log records, so the attributes
// have to reach the backend bridge — which sits below the telemetry handler,
// under multiHandler, and never sees slog.HandlerOptions.
func TestCallsite_CodeAttributesReachTheBackendBridge(t *testing.T) {
	var buf bytes.Buffer
	backend, logger := callsiteBridgeLogger(t, &buf, "false", "true")

	_, file, line, _ := runtime.Caller(0)
	logger.Info("callsite-bridged")

	bridged := bridgedRecord(t, backend)
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

// The code attributes are for the exported record and stop there.
//
// PROVIDE_LOG_CODE_ATTRIBUTES is specified as "attach code attributes to OTel
// log records", and Python and TypeScript attach them to the OTLP record alone —
// neither one's console output carries a code.* key with the knob on. Rendering
// them locally would also print runtime.Frame.File, the absolute path the
// *compiling* machine had, on every line: exactly the leak `filename` reports a
// base name to avoid.
func TestCallsite_CodeAttributesStopAtTheBridge(t *testing.T) {
	var buf bytes.Buffer
	backend, logger := callsiteBridgeLogger(t, &buf, "true", "true")
	logger.Info("callsite-bridge-only")

	rec := decodeRecord(t, &buf)
	for _, key := range []string{_attrCodeFilePath, _attrCodeFunctionName, _attrCodeLineNumber} {
		if _, present := rec[key]; present {
			t.Errorf("%s is rendered locally; the knob attaches it to the exported record", key)
		}
	}
	// The record fields are the ones that belong on every renderer, and they
	// reach the bridge too — one capture, two audiences.
	if rec["filename"] != _thisFile {
		t.Errorf("filename is %v, want %q", rec["filename"], _thisFile)
	}
	bridged := bridgedRecord(t, backend)
	if bridged["filename"] != _thisFile {
		t.Errorf("bridged filename is %v, want %q", bridged["filename"], _thisFile)
	}
	if _, present := bridged[_attrCodeFilePath]; !present {
		t.Error("bridged record carries no code.file.path")
	}
}

// Attaching the code attributes to the bridge must not depend on the bridge
// being reached through a particular constructor: the package logger, which
// slog.Default() also serves, rebuilds the chain separately.
func TestCallsite_CodeAttributesReachTheDefaultLoggersBridge(t *testing.T) {
	var buf bytes.Buffer
	backend, _ := callsiteBridgeLogger(t, &buf, "false", "true")

	Logger().Info("callsite-default-bridged")

	if _, present := bridgedRecord(t, backend)[_attrCodeFilePath]; !present {
		t.Error("the package logger's bridge carries no code.file.path")
	}
}

// With the knob off, nothing attaches them anywhere.
func TestCallsite_CodeAttributesDisabledLeavesTheBridgeClean(t *testing.T) {
	var buf bytes.Buffer
	backend, logger := callsiteBridgeLogger(t, &buf, "true", "false")
	logger.Info("callsite-bridge-no-code")

	bridged := bridgedRecord(t, backend)
	for _, key := range []string{_attrCodeFilePath, _attrCodeFunctionName, _attrCodeLineNumber} {
		if _, present := bridged[key]; present {
			t.Errorf("%s bridged with PROVIDE_LOG_CODE_ATTRIBUTES=false", key)
		}
	}
}

// The code attributes shadow a caller's own keys of the same name, the way the
// record fields do — the bridge is where they collide.
func TestCallsite_CodeAttributesShadowCallerSuppliedKeys(t *testing.T) {
	var buf bytes.Buffer
	backend, logger := callsiteBridgeLogger(t, &buf, "false", "true")

	_, file, _, _ := runtime.Caller(0)
	logger.Info("callsite-bridge-shadow", _attrCodeFilePath, "/somewhere/else.go")

	if got := bridgedRecord(t, backend)[_attrCodeFilePath]; got != file {
		t.Errorf("bridged code.file.path is %v, want the callsite's %q", got, file)
	}
}

// The wrapper is a slog.Handler, so it has to survive With and WithGroup.
//
// Nothing in the chain reaches it that way today — the telemetry handler folds
// bound attributes into the record itself rather than delegating downward — but
// a wrapper that returned its bare `next` on either call would drop the code
// attributes for the first caller that did, silently and only for the loggers
// built through With.
func TestCodeAttrsHandler_SurvivesWithAttrsAndWithGroup(t *testing.T) {
	var buf bytes.Buffer
	handler := (&_codeAttrsHandler{next: slog.NewJSONHandler(&buf, nil)}).
		WithAttrs([]slog.Attr{slog.String("bound", "yes")}).
		WithGroup("g")

	ctx := context.Background()
	if !handler.Enabled(ctx, slog.LevelInfo) {
		t.Fatal("wrapper reports Info disabled; it must defer to the handler it wraps")
	}

	var pcs [1]uintptr
	runtime.Callers(1, pcs[:])
	_, file, line, _ := runtime.Caller(0)
	if err := handler.Handle(ctx, slog.NewRecord(time.Now(), slog.LevelInfo, "wrapped", pcs[0])); err != nil {
		t.Fatalf("handle failed: %v", err)
	}

	rec := decodeRecord(t, &buf)
	if rec["bound"] != "yes" {
		t.Errorf("bound attribute lost through WithAttrs: %#v", rec)
	}
	group, ok := rec["g"].(map[string]any)
	if !ok {
		t.Fatalf("no 'g' group in %#v — WithGroup was dropped", rec)
	}
	if group[_attrCodeFilePath] != file {
		t.Errorf("code.file.path is %v, want %q", group[_attrCodeFilePath], file)
	}
	// runtime.Callers(1) names this line, one above the runtime.Caller pair.
	if want := float64(line - 1); group[_attrCodeLineNumber] != want {
		t.Errorf("code.line.number is %v, want %v", group[_attrCodeLineNumber], want)
	}
}

// A record carrying no resolvable callsite reaches the bridge unchanged rather
// than with an empty path and a zero line.
func TestCallsite_BridgeAttachesNothingWithoutAFrame(t *testing.T) {
	var buf bytes.Buffer
	backend, _ := callsiteBridgeLogger(t, &buf, "false", "true")

	record := slog.NewRecord(time.Now(), slog.LevelInfo, "callsite-bridge-no-pc", 0)
	if err := Logger().Handler().Handle(context.Background(), record); err != nil {
		t.Fatalf("handle failed: %v", err)
	}

	bridged := bridgedRecord(t, backend)
	for _, key := range []string{_attrCodeFilePath, _attrCodeFunctionName, _attrCodeLineNumber} {
		if _, present := bridged[key]; present {
			t.Errorf("%s bridged for a record with no PC", key)
		}
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
