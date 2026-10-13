// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

// Canonical signal pipeline order — spec/pipeline_fixtures.yaml.
//
// Every exit path through the pipeline is a subsequence of the canonical stage
// order: a stage may be skipped, but two stages may never swap places, and the
// backpressure ticket is accounted for on every path including rejections.
//
// As in the TypeScript, Rust and C# suites, the stages are observed on the
// real logger rather than on a pipeline built for the test. The payload stages
// are detected by the mark each actually leaves: the local writer and the
// backend bridge are both called in-line, so each records what had already
// happened to the record when it ran — which is an order, not just a set. The
// gates and the bookkeeping around them leave no mark on a refused record, so
// those report through _pipelineStageHook, and every case is compared against
// the fixture's sequence whole, release included.

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"

	"gopkg.in/yaml.v3"
)

type _pipelineCase struct {
	ID       string   `yaml:"id"`
	Expected []string `yaml:"expected"`
}

type _pipelineFixture struct {
	Events []string        `yaml:"events"`
	Cases  []_pipelineCase `yaml:"cases"`
}

func _loadPipelineFixture(t *testing.T) _pipelineFixture {
	t.Helper()
	path := filepath.Join("..", "spec", "pipeline_fixtures.yaml")
	raw, err := os.ReadFile(path) //nolint:gosec // fixed in-repo fixture path
	if err != nil {
		t.Fatalf("reading %s: %v", path, err)
	}
	var fixture _pipelineFixture
	if err := yaml.Unmarshal(raw, &fixture); err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	if len(fixture.Events) == 0 || len(fixture.Cases) == 0 {
		t.Fatalf("%s declared no events or no cases", path)
	}
	return fixture
}

func TestPipelineFixture_EveryPathIsASubsequenceOfTheCanonicalOrder(t *testing.T) {
	fixture := _loadPipelineFixture(t)
	for _, c := range fixture.Cases {
		var ordered []string
		for _, event := range fixture.Events {
			if slices.Contains(c.Expected, event) {
				ordered = append(ordered, event)
			}
		}
		if !slices.Equal(ordered, c.Expected) {
			t.Errorf("%s reorders the canonical stages: %v", c.ID, c.Expected)
		}
	}
}

func TestPipelineFixture_EveryPathReleasesExactlyOnce(t *testing.T) {
	for _, c := range _loadPipelineFixture(t).Cases {
		n := 0
		for _, event := range c.Expected {
			if event == "release" {
				n++
			}
		}
		if n != 1 {
			t.Errorf("%s releases %d times, want 1", c.ID, n)
		}
	}
}

// _pipelineObserver records, in call order, each stage the record reached:
// the gates through the hook, the payload stages from the sinks.
type _pipelineObserver struct {
	mu        sync.Mutex
	stages    []string
	backendFn func() error
}

func (o *_pipelineObserver) push(stage string) {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.stages = append(o.stages, stage)
}

// _healthNotYetCounted marks a sink that ran after the health stage had
// already counted the record — health belongs after every sink.
func (o *_pipelineObserver) _healthNotYetCounted(sink string) {
	if GetHealthSnapshot().LogsEmitted != 0 || GetHealthSnapshot().LogsExportFailures != 0 {
		o.push("health-before-" + sink)
	}
}

// _pipelineLocal is the host's log writer: the "local" sink. The rendered
// bytes show whether hardening and PII had run, and the receipt collector
// whether a receipt had been issued, before the record was written.
type _pipelineLocal struct{ obs *_pipelineObserver }

func (w _pipelineLocal) Write(p []byte) (int, error) {
	line := string(p)
	if !strings.Contains(line, "pipeline.probe") {
		return len(p), nil
	}
	if strings.Contains(line, `"deep":{"a":"***"}`) {
		w.obs.push("hardening")
	}
	if strings.Contains(line, `"password":"***"`) && !strings.Contains(line, "s3cr3t") {
		w.obs.push("pii")
	}
	if len(GetEmittedReceiptsForTests()) > 0 {
		w.obs.push("receipt")
	}
	w.obs.push("local")
	w.obs._healthNotYetCounted("local")
	return len(p), nil
}

type _pipelineBackendHandler struct{ obs *_pipelineObserver }

func (h _pipelineBackendHandler) Enabled(context.Context, slog.Level) bool { return true }
func (h _pipelineBackendHandler) WithAttrs([]slog.Attr) slog.Handler       { return h }
func (h _pipelineBackendHandler) WithGroup(string) slog.Handler            { return h }
func (h _pipelineBackendHandler) Handle(_ context.Context, r slog.Record) error {
	if r.Message != "pipeline.probe" {
		return nil
	}
	h.obs.push("backend")
	h.obs._healthNotYetCounted("backend")
	if h.obs.backendFn != nil {
		return h.obs.backendFn()
	}
	return nil
}

// _pipelineBackend supplies only the log bridge; every other capability is
// the inert one _erroringBackend already provides.
type _pipelineBackend struct {
	_erroringBackend
	handler slog.Handler
}

func (b *_pipelineBackend) LoggerHandler(string) slog.Handler { return b.handler }

// _pipelineRun configures one exit path through the pipeline.
type _pipelineRun struct {
	backend    bool
	backendErr error
	gates      func()
}

// _observePipeline emits one record through the real setup-installed logger
// and returns the stages it passed, in the order they happened.
func _observePipeline(t *testing.T, run _pipelineRun) []string {
	t.Helper()
	resetSetupState(t)
	ResetReceiptsForTests()
	t.Cleanup(func() {
		_pipelineStageHook.Store(nil)
		resetSetupState(t)
		ResetReceiptsForTests()
		ResetConsentForTests()
	})

	obs := &_pipelineObserver{}
	if run.backendErr != nil {
		obs.backendFn = func() error { return run.backendErr }
	}
	if run.backend {
		RegisterBackend("pipeline-order", &_pipelineBackend{handler: _pipelineBackendHandler{obs: obs}})
		t.Cleanup(func() { UnregisterBackend("pipeline-order") })
	}

	cfg := DefaultTelemetryConfig()
	cfg.ServiceName = "pipeline-svc"
	cfg.Logging.Format = LogFormatJSON
	cfg.Logging.Level = "TRACE"
	cfg.Logging.Sanitize = true
	cfg.Security.MaxNestingDepth = 2
	if _, err := SetupTelemetry(WithConfig(cfg), WithLogOutput(_pipelineLocal{obs: obs})); err != nil {
		t.Fatalf("setup: %v", err)
	}
	if err := EnableReceipts(ReceiptOptions{Enabled: true, ServiceName: "pipeline-svc"}); err != nil {
		t.Fatalf("receipts: %v", err)
	}
	// After setup, which installs the config's policies over anything set
	// earlier; and on a fresh health snapshot, so each counter read in a sink
	// is this record's alone.
	SetQueuePolicy(QueuePolicy{LogsMaxSize: 1})
	run.gates()
	_resetHealth()

	hook := obs.push
	_pipelineStageHook.Store(&hook)
	Logger().Info("pipeline.probe",
		"deep", map[string]any{"a": map[string]any{"b": "unreachable"}},
		"password", "s3cr3t", // pragma: allowlist secret
	)
	_pipelineStageHook.Store(nil)

	obs.mu.Lock()
	defer obs.mu.Unlock()
	return slices.Clone(obs.stages)
}

func _ticketAvailable() bool {
	ticket := TryAcquire(signalLogs)
	if ticket == nil {
		return false
	}
	Release(ticket)
	return true
}

func _noGates() {}

// Every fixture case, run on the real logger and compared whole. A case added
// to the fixture without a run here fails rather than passing unexercised.
func TestPipelineOrder_EveryFixtureCaseMatchesExactly(t *testing.T) {
	var held *QueueTicket
	runs := map[string]_pipelineRun{
		"consent_rejection":  {gates: func() { SetConsentLevel(ConsentNone) }},
		"sampling_rejection": {gates: func() { _, _ = SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0}) }},
		"queue_rejection":    {gates: func() { held = TryAcquire(signalLogs) }},
		"local_only_success": {gates: _noGates},
		"backend_success":    {backend: true, gates: _noGates},
		"backend_failure":    {backend: true, backendErr: errors.New("collector refused"), gates: _noGates},
	}
	for _, c := range _loadPipelineFixture(t).Cases {
		t.Run(c.ID, func(t *testing.T) {
			run, ok := runs[c.ID]
			if !ok {
				t.Fatalf("fixture case %q has no run in this suite", c.ID)
			}
			held = nil
			observed := _observePipeline(t, run)
			if !slices.Equal(observed, c.Expected) {
				t.Fatalf("observed %v, want %v", observed, c.Expected)
			}
			if held != nil {
				// The refused record must not have taken the slot it was
				// refused: with the only ticket held the queue stays full.
				if _ticketAvailable() {
					t.Fatal("the refused record freed a slot it never held")
				}
				Release(held)
			}
			if !_ticketAvailable() {
				t.Fatal("the record's ticket was not returned")
			}
		})
	}
}

// What the health stage counts on each path: an admitted record is emitted
// (and, if the backend refused it, an export failure too); a refused one is a
// drop, whichever gate refused it — consent included.
func TestPipelineOrder_HealthCountsEachPathOnce(t *testing.T) {
	type counts struct{ emitted, dropped, failures int64 }
	cases := map[string]struct {
		run  _pipelineRun
		want counts
	}{
		"consent":  {_pipelineRun{gates: func() { SetConsentLevel(ConsentNone) }}, counts{0, 1, 0}},
		"sampling": {_pipelineRun{gates: func() { _, _ = SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0}) }}, counts{0, 1, 0}},
		"admitted": {_pipelineRun{backend: true, gates: _noGates}, counts{1, 0, 0}},
		"failed":   {_pipelineRun{backend: true, backendErr: errors.New("refused"), gates: _noGates}, counts{1, 0, 1}},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			_observePipeline(t, tc.run)
			snap := GetHealthSnapshot()
			if got := (counts{snap.LogsEmitted, snap.LogsDropped, snap.LogsExportFailures}); got != tc.want {
				t.Fatalf("counted %+v, want %+v", got, tc.want)
			}
		})
	}
}
