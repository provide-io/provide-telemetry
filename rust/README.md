# Rust Crate

SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc

`provide-telemetry` ships a Rust crate in this repo under `rust/`.

## Features

- Default build: fallback telemetry primitives, context guards, schema enforcement, and in-process metrics.
- `otel`: enables OpenTelemetry dependencies used by the Rust E2E/OpenObserve paths.

Install locally from the repo:

```bash
cargo build --manifest-path rust/Cargo.toml
cargo build --manifest-path rust/Cargo.toml --features otel
```

## Examples

- `cargo run --manifest-path rust/Cargo.toml --example telemetry_01_basic`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_02_w3c_propagation`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_03_sampling_and_backpressure`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_04_runtime_reconfigure`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_05_pii_and_cardinality_policy`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_06_exporter_resilience_modes`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_07_slo_and_health_snapshot`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_08_full_hardening_profile`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_09_error_handling_and_degradation`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_10_performance_metrics`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_11_lazy_loading_proof`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_12_error_fingerprint_and_sessions`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_13_security_hardening`
- `cargo run --manifest-path rust/Cargo.toml --example telemetry_14_data_governance`
- `cargo run --manifest-path rust/Cargo.toml --features otel --example e2e_cross_language_client`
- `cargo run --manifest-path rust/Cargo.toml --features otel --example e2e_cross_language_server -- --port 18765`

The Rust example suite now covers the same numbered telemetry examples as Python and TypeScript, plus the Rust OTLP E2E client/server pair used by the cross-language verification flow.
