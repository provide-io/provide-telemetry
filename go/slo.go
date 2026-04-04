// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"log/slog"
	"strconv"
	"strings"
)

// Error classification category constants.
const (
	_errCatClientError  = "client_error"
	_errCatServerError  = "server_error"
	_errCatTimeout      = "timeout"
	_errCatUnknown      = "unknown"
	_errSevCritical     = "critical"
	_errSevWarning      = "warning"
	_errSevInfo         = "info"
)

// Package-level RED metric instruments (Rate, Errors, Duration).
var (
	_redRequestCounter    Counter   = NewCounter("slo.red.requests", WithDescription("RED request rate"))
	_redErrorCounter      Counter   = NewCounter("slo.red.errors", WithDescription("RED error count"))
	_redDurationHistogram Histogram = NewHistogram("slo.red.duration_ms", WithDescription("RED request duration"), WithUnit("ms"))
)

// Package-level USE metric instrument (Utilization, Saturation, Errors).
var _useUtilizationGauge Gauge = NewGauge("slo.use.utilization", WithDescription("USE utilization percentage"), WithUnit("%"))

// ClassifyError returns a map of error taxonomy fields for the given exception
// name and HTTP status code.
//
// Keys returned: "error.type", "http.status_code", "error.category", "error.severity".
func ClassifyError(excName string, statusCode int) map[string]string {
	result := map[string]string{
		"error.type":       excName,
		"http.status_code": strconv.Itoa(statusCode),
	}

	isTimeout := statusCode == 0 || strings.Contains(strings.ToLower(excName), "timeout")

	switch {
	case isTimeout:
		result["error.category"] = _errCatTimeout
		result["error.severity"] = _errSevInfo
	case statusCode >= 500:
		result["error.category"] = _errCatServerError
		result["error.severity"] = _errSevCritical
	case statusCode >= 400:
		result["error.category"] = _errCatClientError
		if statusCode == 429 {
			result["error.severity"] = _errSevCritical
		} else {
			result["error.severity"] = _errSevWarning
		}
	default:
		result["error.category"] = _errCatUnknown
		result["error.severity"] = _errSevInfo
	}

	return result
}

// RecordREDMetrics records Rate/Errors/Duration metrics for an HTTP request.
// It increments the request counter, conditionally increments the error counter
// for status codes >= 400, and records the duration.
func RecordREDMetrics(route, method string, statusCode int, durationMs float64) {
	ctx := context.Background()
	attrs := []slog.Attr{
		slog.String("route", route),
		slog.String("method", method),
		slog.String("status_code", strconv.Itoa(statusCode)),
	}
	_redRequestCounter.Add(ctx, 1, attrs...)
	if statusCode >= 400 {
		_redErrorCounter.Add(ctx, 1, attrs...)
	}
	_redDurationHistogram.Record(ctx, durationMs, attrs...)
}

// RecordUSEMetrics records the Utilization metric for a named resource.
func RecordUSEMetrics(resource string, utilizationPercent int) {
	ctx := context.Background()
	_useUtilizationGauge.Set(ctx, float64(utilizationPercent), slog.String("resource", resource))
}
