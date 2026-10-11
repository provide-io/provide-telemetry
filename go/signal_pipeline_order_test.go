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
// real logger rather than on a pipeline built for the test, so each stage is
// detected by the mark it actually leaves. Go can do slightly better than
// presence for the sinks: the local writer and the backend bridge are both
// called in-line, so each records what had already happened when it ran —
// which is an order, not just a set.

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

func (f _pipelineFixture) expected(t *testing.T, id string) []string {
	t.Helper()
	for _, c := range f.Cases {
		if c.ID == id {
			return c.Expected
		}
	}
	t.Fatalf("fixture carries no case %q", id)
	return nil
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

// _pipelineObserver records, in call order, each sink the record reached and
// what was already true of the record and the runtime when it got there.
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

// _pipelineLocal is the host's log writer: the "local" sink. Reaching it at
// all means sampling and backpressure admitted the record, and the rendered
// bytes show whether hardening and PII had run, and the receipt collector
// whether a receipt had been issued, before the record was written.
type _pipelineLocal struct{ obs *_pipelineObserver }

func (w _pipelineLocal) Write(p []byte) (int, error) {
	line := string(p)
	if !strings.Contains(line, "pipeline.probe") {
		return len(p), nil
	}
	w.obs.push("sampling")
	w.obs.push("backpressure")
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
	// Export failures are the health stage that follows the backend: none
	// may have been counted yet for this record.
	if GetHealthSnapshot().LogsExportFailures != 0 {
		h.obs.push("health-before-backend")
	}
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

// _observePipeline emits one record through the real setup-installed logger
// and returns the stages it left a mark on, in the order they happened.
func _observePipeline(t *testing.T, backendErr error, gates func()) []string {
	t.Helper()
	resetSetupState(t)
	ResetReceiptsForTests()
	t.Cleanup(func() {
		resetSetupState(t)
		ResetReceiptsForTests()
		ResetConsentForTests()
	})

	obs := &_pipelineObserver{}
	if backendErr != nil {
		obs.backendFn = func() error { return backendErr }
	}
	RegisterBackend("pipeline-order", &_pipelineBackend{handler: _pipelineBackendHandler{obs: obs}})
	t.Cleanup(func() { UnregisterBackend("pipeline-order") })

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
	// earlier.
	gates()

	Logger().Info("pipeline.probe",
		"deep", map[string]any{"a": map[string]any{"b": "unreachable"}},
		"password", "s3cr3t", // pragma: allowlist secret
	)

	// Reaching the logger at all means consent was consulted.
	observed := append([]string{"consent"}, obs.stages...)
	if GetHealthSnapshot().LogsEmitted > 0 {
		observed = append(observed, "health")
	}
	return observed
}

// _observable keeps the fixture stages this suite can see: release is checked
// through queue capacity instead, because a ticket leaves no other mark.
func _observable(stages []string) []string {
	return slices.DeleteFunc(slices.Clone(stages), func(s string) bool { return s == "release" })
}

func _ticketAvailable() bool {
	ticket := TryAcquire(signalLogs)
	if ticket == nil {
		return false
	}
	Release(ticket)
	return true
}

func TestPipelineOrder_BackendSuccessRunsEveryStageInOrder(t *testing.T) {
	fixture := _loadPipelineFixture(t)
	observed := _observePipeline(t, nil, func() { SetQueuePolicy(QueuePolicy{LogsMaxSize: 1}) })

	if want := _observable(fixture.expected(t, "backend_success")); !slices.Equal(observed, want) {
		t.Fatalf("observed %v, want %v", observed, want)
	}
	if !_ticketAvailable() {
		t.Fatal("the record's ticket was not released")
	}
}

func TestPipelineOrder_BackendFailureStillRecordsHealthAfterBackend(t *testing.T) {
	fixture := _loadPipelineFixture(t)
	observed := _observePipeline(t, errors.New("collector refused"),
		func() { SetQueuePolicy(QueuePolicy{LogsMaxSize: 1}) })

	if want := _observable(fixture.expected(t, "backend_failure")); !slices.Equal(observed, want) {
		t.Fatalf("observed %v, want %v", observed, want)
	}
	if got := GetHealthSnapshot().LogsExportFailures; got != 1 {
		t.Fatalf("export failure counted %d times after the backend refused, want 1", got)
	}
	if !_ticketAvailable() {
		t.Fatal("a failed export kept its ticket")
	}
}

// Rejected at admission, nothing past the gate leaves a mark: no sink is
// reached and nothing is counted as emitted.
func TestPipelineOrder_RejectionsStopAtAdmissionAndKeepCapacity(t *testing.T) {
	cases := map[string]func(){
		"consent_rejection":  func() { SetConsentLevel(ConsentNone) },
		"sampling_rejection": func() { _, _ = SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0}) },
	}
	for id, gates := range cases {
		t.Run(id, func(t *testing.T) {
			fixture := _loadPipelineFixture(t)
			_ = fixture.expected(t, id)
			observed := _observePipeline(t, nil, func() {
				gates()
				SetQueuePolicy(QueuePolicy{LogsMaxSize: 1})
			})
			if !slices.Equal(observed, []string{"consent"}) {
				t.Fatalf("observed %v, want only consent", observed)
			}
			if !_ticketAvailable() {
				t.Fatal("a rejected record took queue capacity")
			}
		})
	}
}

// A record refused by backpressure must not consume the slot it was refused:
// with the only ticket held, the queue is full and stays full.
func TestPipelineOrder_QueueRejectionLeaksNoCapacity(t *testing.T) {
	fixture := _loadPipelineFixture(t)
	_ = fixture.expected(t, "queue_rejection")
	var held *QueueTicket
	observed := _observePipeline(t, nil, func() {
		SetQueuePolicy(QueuePolicy{LogsMaxSize: 1})
		held = TryAcquire(signalLogs)
	})
	if held == nil {
		t.Fatal("the test must hold the only slot")
	}
	if !slices.Equal(observed, []string{"consent"}) {
		t.Fatalf("observed %v, want only consent", observed)
	}
	if got := GetHealthSnapshot().LogsDropped; got != 1 {
		t.Fatalf("queue rejection counted %d drops, want 1", got)
	}
	if _ticketAvailable() {
		t.Fatal("the refused record freed a slot it never held")
	}
	Release(held)
	if !_ticketAvailable() {
		t.Fatal("releasing the held ticket did not restore capacity")
	}
}
