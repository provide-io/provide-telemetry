// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"context"
	"fmt"
	"testing"
)

// ── Event name ──────────────────────────────────────────────────────────────

func BenchmarkEventName_3Segments(b *testing.B) {
	for b.Loop() {
		_, _ = EventName("auth", "login", "success")
	}
}

func BenchmarkEventName_5Segments(b *testing.B) {
	for b.Loop() {
		_, _ = EventName("payment", "subscription", "renewal", "charge", "success")
	}
}

// ── Sampling ────────────────────────────────────────────────────────────────

func BenchmarkShouldSample_RateOne(b *testing.B) {
	_resetSamplingPolicies()
	_, _ = SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 1.0})
	b.ResetTimer()
	for b.Loop() {
		_, _ = ShouldSample(signalLogs, "")
	}
}

func BenchmarkShouldSample_RateZero(b *testing.B) {
	_resetSamplingPolicies()
	_, _ = SetSamplingPolicy(signalLogs, SamplingPolicy{DefaultRate: 0.0})
	b.ResetTimer()
	for b.Loop() {
		_, _ = ShouldSample(signalLogs, "")
	}
}

func BenchmarkShouldSample_WithOverride(b *testing.B) {
	_resetSamplingPolicies()
	_, _ = SetSamplingPolicy(signalLogs, SamplingPolicy{
		DefaultRate: 0.5,
		Overrides:   map[string]float64{"auth.login": 1.0},
	})
	b.ResetTimer()
	for b.Loop() {
		_, _ = ShouldSample(signalLogs, "auth.login")
	}
}

// ── PII sanitization ────────────────────────────────────────────────────────

func BenchmarkSanitizePayload_SmallFlat(b *testing.B) {
	_resetPIIRules()
	payload := map[string]any{
		"password":   "secret", //nolint:gosec // benchmark data
		"token":      "abc",    //nolint:gosec // benchmark data
		"request_id": "r1",
	}
	b.ResetTimer()
	for b.Loop() {
		SanitizePayload(payload, true, 8)
	}
}

func BenchmarkSanitizePayload_LargeFlat(b *testing.B) {
	_resetPIIRules()
	payload := make(map[string]any, 52) //nolint:mnd // benchmark data
	for i := range 50 {
		payload[fmt.Sprintf("field_%d", i)] = fmt.Sprintf("value_%d", i)
	}
	payload["password"] = "secret" //nolint:gosec // pragma: allowlist secret
	payload["token"] = "abc"       //nolint:gosec // benchmark data
	b.ResetTimer()
	for b.Loop() {
		SanitizePayload(payload, true, 8)
	}
}

func BenchmarkSanitizePayload_Disabled(b *testing.B) {
	_resetPIIRules()
	payload := map[string]any{
		"password":   "secret", //nolint:gosec // benchmark data
		"token":      "abc",    //nolint:gosec // benchmark data
		"request_id": "r1",
	}
	b.ResetTimer()
	for b.Loop() {
		SanitizePayload(payload, false, 8)
	}
}

// ── Backpressure ────────────────────────────────────────────────────────────

func BenchmarkTryAcquireRelease_Unlimited(b *testing.B) {
	_resetQueuePolicy()
	SetQueuePolicy(QueuePolicy{}) // unlimited
	b.ResetTimer()
	for b.Loop() {
		if TryAcquire(signalLogs) {
			Release(signalLogs)
		}
	}
}

// ── Health ───────────────────────────────────────────────────────────────────

func BenchmarkGetHealthSnapshot(b *testing.B) {
	for b.Loop() {
		GetHealthSnapshot()
	}
}

// ── Metrics ─────────────────────────────────────────────────────────────────

func BenchmarkCounter_Add(b *testing.B) {
	c := NewCounter("bench_counter")
	ctx := context.Background()
	b.ResetTimer()
	for b.Loop() {
		c.Add(ctx, 1)
	}
}

func BenchmarkGauge_Set(b *testing.B) {
	g := NewGauge("bench_gauge")
	ctx := context.Background()
	b.ResetTimer()
	for b.Loop() {
		g.Set(ctx, 42.0)
	}
}

func BenchmarkHistogram_Record(b *testing.B) {
	h := NewHistogram("bench_histogram")
	ctx := context.Background()
	b.ResetTimer()
	for b.Loop() {
		h.Record(ctx, 3.14)
	}
}
