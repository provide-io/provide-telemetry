// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use criterion::{criterion_group, criterion_main, Criterion};

fn bench_sampling(c: &mut Criterion) {
    let _ = provide_telemetry::set_sampling_policy(
        provide_telemetry::Signal::Logs,
        provide_telemetry::SamplingPolicy {
            default_rate: 0.5,
            overrides: Default::default(),
        },
    );
    c.bench_function("should_sample_logs", |b| {
        b.iter(|| provide_telemetry::should_sample(provide_telemetry::Signal::Logs, Some("test")))
    });
}

fn bench_pii_sanitize(c: &mut Criterion) {
    let payload = serde_json::json!({
        "event": "auth.login.ok",
        "user": "alice",
        "password": "secret123", // pragma: allowlist secret
        "token": "tok_abc_very_long_value_here",
    });
    c.bench_function("sanitize_payload", |b| {
        b.iter(|| provide_telemetry::sanitize_payload(&payload, true, 8))
    });
}

fn bench_parse_baggage(c: &mut Criterion) {
    let raw = "userId=alice,tenant=acme,requestId=req-123;ttl=30,env=prod";
    c.bench_function("parse_baggage", |b| {
        b.iter(|| provide_telemetry::parse_baggage(raw))
    });
}

criterion_group!(
    benches,
    bench_sampling,
    bench_pii_sanitize,
    bench_parse_baggage
);
criterion_main!(benches);
