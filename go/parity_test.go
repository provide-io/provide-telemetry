// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

// parity_test.go is the entry point for Go behavioral parity tests.
// All tests have been split into focused files:
//   - parity_sampling_test.go    — sampling rate and signal validation
//   - parity_pii_test.go         — PII hash, truncate, redact, drop, secret detection
//   - parity_propagation_test.go — W3C traceparent/tracestate/baggage guards
//   - parity_schema_test.go      — event name validation (lenient/strict modes)
//   - parity_slo_test.go         — SLO error classification
//   - parity_backpressure_test.go — backpressure queue policy
//   - parity_cardinality_test.go  — cardinality limit clamping
//   - parity_config_test.go       — OTLP header parsing and error fingerprinting
//   - parity_endpoint_test.go     — endpoint URL validation (valid/invalid fixtures)

package telemetry
