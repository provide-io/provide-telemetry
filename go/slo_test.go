// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"testing"
)

// --- ClassifyError tests ---

func TestClassifyError4xx(t *testing.T) {
	m := ClassifyError("BadRequest", 400)
	if got := m["error.category"]; got != "client_error" {
		t.Fatalf("expected client_error, got %s", got)
	}
	if got := m["error.severity"]; got != "warning" {
		t.Fatalf("expected warning, got %s", got)
	}
	if got := m["error.type"]; got != "BadRequest" {
		t.Fatalf("expected BadRequest, got %s", got)
	}
	if got := m["http.status_code"]; got != "400" {
		t.Fatalf("expected 400, got %s", got)
	}
}

func TestClassifyError429(t *testing.T) {
	m := ClassifyError("TooManyRequests", 429)
	if got := m["error.category"]; got != "client_error" {
		t.Fatalf("expected client_error, got %s", got)
	}
	if got := m["error.severity"]; got != "critical" {
		t.Fatalf("expected critical, got %s", got)
	}
}

func TestClassifyError5xx(t *testing.T) {
	m := ClassifyError("InternalServerError", 500)
	if got := m["error.category"]; got != "server_error" {
		t.Fatalf("expected server_error, got %s", got)
	}
	if got := m["error.severity"]; got != "critical" {
		t.Fatalf("expected critical, got %s", got)
	}
}

func TestClassifyErrorStatus0Timeout(t *testing.T) {
	m := ClassifyError("ConnectionError", 0)
	if got := m["error.category"]; got != "timeout" {
		t.Fatalf("expected timeout, got %s", got)
	}
	if got := m["error.severity"]; got != "info" {
		t.Fatalf("expected info, got %s", got)
	}
}

func TestClassifyErrorExcNameTimeout(t *testing.T) {
	m := ClassifyError("ReadTimeout", 503)
	if got := m["error.category"]; got != "timeout" {
		t.Fatalf("expected timeout, got %s", got)
	}
	if got := m["error.severity"]; got != "info" {
		t.Fatalf("expected info, got %s", got)
	}
}

func TestClassifyError2xx(t *testing.T) {
	m := ClassifyError("", 200)
	if got := m["error.category"]; got != "unknown" {
		t.Fatalf("expected unknown, got %s", got)
	}
	if got := m["error.severity"]; got != "info" {
		t.Fatalf("expected info, got %s", got)
	}
}

// --- RecordREDMetrics tests ---

func TestRecordREDMetrics200(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()

	// Swap out the package-level instruments with fresh ones we can inspect.
	origReq := _redRequestCounter
	origErr := _redErrorCounter
	origDur := _redDurationHistogram
	defer func() {
		_redRequestCounter = origReq
		_redErrorCounter = origErr
		_redDurationHistogram = origDur
	}()

	reqC := NewCounter("test.slo.red.req")
	errC := NewCounter("test.slo.red.err")
	durH := NewHistogram("test.slo.red.dur")
	_redRequestCounter = reqC
	_redErrorCounter = errC
	_redDurationHistogram = durH

	RecordREDMetrics("/api/v1/health", "GET", 200, 12.5)

	if got := reqC.(*_atomicCounter).Value(); got != 1 {
		t.Fatalf("expected request counter 1, got %d", got)
	}
	if got := errC.(*_atomicCounter).Value(); got != 0 {
		t.Fatalf("expected error counter 0, got %d", got)
	}
	if got := durH.(*_atomicHistogram).Count(); got != 1 {
		t.Fatalf("expected duration count 1, got %d", got)
	}
}

func TestRecordREDMetrics500(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()

	origReq := _redRequestCounter
	origErr := _redErrorCounter
	origDur := _redDurationHistogram
	defer func() {
		_redRequestCounter = origReq
		_redErrorCounter = origErr
		_redDurationHistogram = origDur
	}()

	reqC := NewCounter("test.slo.red.req.500")
	errC := NewCounter("test.slo.red.err.500")
	durH := NewHistogram("test.slo.red.dur.500")
	_redRequestCounter = reqC
	_redErrorCounter = errC
	_redDurationHistogram = durH

	RecordREDMetrics("/api/v1/crash", "POST", 500, 99.9)

	if got := reqC.(*_atomicCounter).Value(); got != 1 {
		t.Fatalf("expected request counter 1, got %d", got)
	}
	if got := errC.(*_atomicCounter).Value(); got != 1 {
		t.Fatalf("expected error counter 1, got %d", got)
	}
	if got := durH.(*_atomicHistogram).Count(); got != 1 {
		t.Fatalf("expected duration count 1, got %d", got)
	}
}

func TestRecordREDMetrics400(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()

	origReq := _redRequestCounter
	origErr := _redErrorCounter
	origDur := _redDurationHistogram
	defer func() {
		_redRequestCounter = origReq
		_redErrorCounter = origErr
		_redDurationHistogram = origDur
	}()

	reqC := NewCounter("test.slo.red.req.400")
	errC := NewCounter("test.slo.red.err.400")
	durH := NewHistogram("test.slo.red.dur.400")
	_redRequestCounter = reqC
	_redErrorCounter = errC
	_redDurationHistogram = durH

	// statusCode == 400 is the boundary: must count as error (>= 400, not > 400)
	RecordREDMetrics("/api/boundary", "GET", 400, 5.0)

	if got := reqC.(*_atomicCounter).Value(); got != 1 {
		t.Fatalf("expected request counter 1, got %d", got)
	}
	if got := errC.(*_atomicCounter).Value(); got != 1 {
		t.Fatalf("expected error counter 1 for status 400, got %d", got)
	}
}

func TestRecordREDMetrics399_NotError(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()

	origErr := _redErrorCounter
	defer func() { _redErrorCounter = origErr }()

	errC := NewCounter("test.slo.red.err.399")
	_redErrorCounter = errC

	RecordREDMetrics("/api/ok", "GET", 399, 1.0)

	if got := errC.(*_atomicCounter).Value(); got != 0 {
		t.Fatalf("expected error counter 0 for status 399, got %d", got)
	}
}

// --- RecordUSEMetrics tests ---

func TestRecordUSEMetrics(t *testing.T) {
	_resetSamplingPolicies()
	_resetQueuePolicy()

	origGauge := _useUtilizationGauge
	defer func() { _useUtilizationGauge = origGauge }()

	g := NewGauge("test.slo.use.util")
	_useUtilizationGauge = g

	RecordUSEMetrics("cpu", 75)

	if got := g.(*_atomicGauge).Value(); got != 75.0 {
		t.Fatalf("expected utilization 75.0, got %f", got)
	}
}
