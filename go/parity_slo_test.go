// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_slo_test.go validates Go behavioral parity for SLO error classification
// against spec/behavioral_fixtures.yaml: HTTP 4xx as client_error, 5xx as
// server_error, 429 as critical client_error, 0 as timeout, 2xx/3xx as unknown,
// and timeout classification by exception name prefix.

package telemetry

import (
	"testing"
)

// ── SLO Classify ─────────────────────────────────────────────────────────────

func TestParity_ClassifyError_400(t *testing.T) {
	m := ClassifyError("BadRequest", 400)
	if m["error.category"] != "client_error" {
		t.Errorf("400 category: want client_error, got %s", m["error.category"])
	}
}

func TestParity_ClassifyError_500(t *testing.T) {
	m := ClassifyError("InternalServerError", 500)
	if m["error.category"] != "server_error" {
		t.Errorf("500 category: want server_error, got %s", m["error.category"])
	}
}

func TestParity_ClassifyError_429(t *testing.T) {
	m := ClassifyError("TooManyRequests", 429)
	if m["error.category"] != "client_error" {
		t.Errorf("429 category: want client_error, got %s", m["error.category"])
	}
	if m["error.severity"] != "critical" {
		t.Errorf("429 severity: want critical, got %s", m["error.severity"])
	}
}

func TestParity_ClassifyError_0(t *testing.T) {
	m := ClassifyError("ConnectionError", 0)
	if m["error.category"] != "timeout" {
		t.Errorf("0 category: want timeout, got %s", m["error.category"])
	}
}

// ── SLO Classify — edge cases ─────────────────────────────────────────────────

func TestParity_ClassifyError_200_Unknown(t *testing.T) {
	result := ClassifyError("", 200)
	if result["error.category"] != "unknown" {
		t.Errorf("expected unknown for 200, got %s", result["error.category"])
	}
}

func TestParity_ClassifyError_301_Unknown(t *testing.T) {
	result := ClassifyError("", 301)
	if result["error.category"] != "unknown" {
		t.Errorf("expected unknown for 301, got %s", result["error.category"])
	}
}

func TestParity_ClassifyError_TimeoutByExcName(t *testing.T) {
	result := ClassifyError("ConnectionTimeoutError", 503)
	if result["error.category"] != "timeout" {
		t.Errorf("expected timeout by exc name, got %s", result["error.category"])
	}
}

func TestParity_ClassifyError_599_ServerError(t *testing.T) {
	result := ClassifyError("ServerError", 599)
	if result["error.category"] != "server_error" {
		t.Errorf("expected server_error for 599, got %s", result["error.category"])
	}
}
