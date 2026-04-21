// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

//go:build !nogovernance

package telemetry

import (
	"context"
	"testing"
)

func TestProviderBackedMetricsRespectConsent(t *testing.T) {
	ResetConsentForTests()
	t.Cleanup(ResetConsentForTests)

	counter, gauge, histogram := setupProviderBackedMetricsForGate(t)
	SetConsentLevel(ConsentNone)

	before := GetHealthSnapshot()
	counter.Add(context.Background(), 1)
	gauge.Set(context.Background(), 2.5)
	histogram.Record(context.Background(), 3.5)
	after := GetHealthSnapshot()

	if after.MetricsEmitted != before.MetricsEmitted {
		t.Fatalf("expected provider-backed metrics to respect consent gate: before=%d after=%d", before.MetricsEmitted, after.MetricsEmitted)
	}
}
