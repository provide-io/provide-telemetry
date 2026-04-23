// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#![cfg(feature = "otel")]

use std::env;
use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
use provide_telemetry::{
    counter, get_health_snapshot, get_logger, get_runtime_status, setup_telemetry,
    shutdown_telemetry, trace, HealthSnapshot,
};

const OTLP_RUNTIME_ENV_KEYS: &[&str] = &[
    "PROVIDE_TELEMETRY_SERVICE_NAME",
    "PROVIDE_TRACE_ENABLED",
    "PROVIDE_METRICS_ENABLED",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_BSP_SCHEDULE_DELAY",
    "OTEL_BLRP_SCHEDULE_DELAY",
    "OTEL_METRIC_EXPORT_INTERVAL",
];

struct MockOtlpCollector {
    endpoint: String,
    stopping: Arc<AtomicBool>,
    wake_addr: String,
    worker: Option<thread::JoinHandle<()>>,
}

impl MockOtlpCollector {
    fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind OTLP mock collector");
        listener
            .set_nonblocking(true)
            .expect("set OTLP mock collector nonblocking");
        let addr = listener.local_addr().expect("mock collector local addr");
        let stopping = Arc::new(AtomicBool::new(false));
        let worker_stopping = Arc::clone(&stopping);
        let wake_addr = addr.to_string();

        let worker = thread::spawn(move || {
            while !worker_stopping.load(Ordering::Relaxed) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        let _ = read_request_path(&mut stream);
                        let _ = stream.write_all(
                            b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                        );
                        let _ = stream.flush();
                    }
                    Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(10));
                    }
                    Err(err) => panic!("mock collector accept failed: {err}"),
                }
            }
        });

        Self {
            endpoint: format!("http://{addr}"),
            stopping,
            wake_addr,
            worker: Some(worker),
        }
    }

}

impl Drop for MockOtlpCollector {
    fn drop(&mut self) {
        self.stopping.store(true, Ordering::Relaxed);
        if let Ok(stream) = TcpStream::connect(&self.wake_addr) {
            let _ = stream.shutdown(Shutdown::Both);
        }
        if let Some(worker) = self.worker.take() {
            worker.join().expect("OTLP mock collector thread");
        }
    }
}

fn read_request_path(stream: &mut TcpStream) -> Option<String> {
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .expect("mock collector read timeout");
    let mut buf = Vec::new();
    let mut chunk = [0_u8; 4096];
    let header_end = loop {
        let read = stream.read(&mut chunk).ok()?;
        if read == 0 {
            return None;
        }
        buf.extend_from_slice(&chunk[..read]);
        if let Some(pos) = buf.windows(4).position(|window| window == b"\r\n\r\n") {
            break pos + 4;
        }
    };

    let headers = std::str::from_utf8(&buf[..header_end]).ok()?;
    let path = headers
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .map(str::to_owned)?;
    let content_length = headers
        .lines()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            if name.eq_ignore_ascii_case("content-length") {
                value.trim().parse::<usize>().ok()
            } else {
                None
            }
        })
        .unwrap_or(0);
    while buf.len() < header_end + content_length {
        let read = stream.read(&mut chunk).ok()?;
        if read == 0 {
            break;
        }
        buf.extend_from_slice(&chunk[..read]);
    }
    Some(path)
}

fn with_runtime_otlp_env(endpoint: &str, test: impl FnOnce()) {
    let mut snapshot = Vec::with_capacity(OTLP_RUNTIME_ENV_KEYS.len());
    for key in OTLP_RUNTIME_ENV_KEYS {
        snapshot.push(((*key).to_string(), env::var(key).ok()));
    }

    // SAFETY: tests are serialised by acquire_test_state_lock at callsites.
    unsafe {
        let logs_endpoint = format!("{endpoint}/v1/logs");
        let traces_endpoint = format!("{endpoint}/v1/traces");
        let metrics_endpoint = format!("{endpoint}/v1/metrics");
        env::set_var(
            "PROVIDE_TELEMETRY_SERVICE_NAME",
            "provide-telemetry-rust-runtime-test",
        );
        env::set_var("PROVIDE_TRACE_ENABLED", "true");
        env::set_var("PROVIDE_METRICS_ENABLED", "true");
        env::set_var("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint);
        env::set_var("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", logs_endpoint);
        env::set_var("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", traces_endpoint);
        env::set_var("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", metrics_endpoint);
        env::set_var("OTEL_BSP_SCHEDULE_DELAY", "50");
        env::set_var("OTEL_BLRP_SCHEDULE_DELAY", "50");
        env::set_var("OTEL_METRIC_EXPORT_INTERVAL", "100");
    }

    test();

    // SAFETY: tests are serialised by acquire_test_state_lock at callsites.
    unsafe {
        for (key, value) in snapshot {
            match value {
                Some(value) => env::set_var(key, value),
                None => env::remove_var(key),
            }
        }
    }
}

fn run_runtime_otlp_smoke(emit_trace: bool, emit_metric: bool) -> HealthSnapshot {
    let collector = MockOtlpCollector::start();
    with_runtime_otlp_env(&collector.endpoint, || {
        setup_telemetry().expect("setup_telemetry should succeed");
        let status = get_runtime_status();
        assert!(
            status.providers.logs,
            "expected logs provider installed after setup, got {status:?}"
        );
        assert!(
            status.providers.traces,
            "expected traces provider installed after setup, got {status:?}"
        );
        assert!(
            status.providers.metrics,
            "expected metrics provider installed after setup, got {status:?}"
        );

        let logger = get_logger(Some("integration.collector"));
        let emit_log = || {
            logger.info("integration.collector.log");
            if emit_metric {
                let requests = counter(
                    "integration.collector.requests",
                    Some("runtime-backed export smoke"),
                    Some("1"),
                );
                requests.add(1.0, None);
            }
        };
        if emit_trace {
            trace("integration.collector.span", emit_log);
        } else {
            emit_log();
        }

        std::thread::sleep(Duration::from_millis(200));
        shutdown_telemetry().expect("shutdown_telemetry should succeed");
        std::thread::sleep(Duration::from_secs(2));
    });

    let health = wait_for_export_health(true, emit_trace, emit_metric, Duration::from_secs(5));

    reset_telemetry_state();
    health
}

fn wait_for_export_health(
    expect_logs: bool,
    expect_traces: bool,
    expect_metrics: bool,
    timeout: Duration,
) -> HealthSnapshot {
    let deadline = Instant::now() + timeout;
    loop {
        let health = get_health_snapshot();
        if export_health_observed(&health, expect_logs, expect_traces, expect_metrics) {
            return health;
        }
        if Instant::now() >= deadline {
            return health;
        }
        std::thread::sleep(Duration::from_millis(25));
    }
}

fn assert_export_health_success(
    health: &HealthSnapshot,
    expect_logs: bool,
    expect_traces: bool,
    expect_metrics: bool,
) {
    if expect_logs {
        assert_eq!(
            health.export_failures_logs, 0,
            "expected log export success, saw health={health:?}"
        );
        assert!(
            health.export_latency_ms_logs > 0.0,
            "expected log export latency, saw health={health:?}"
        );
    }
    if expect_traces {
        assert_eq!(
            health.export_failures_traces, 0,
            "expected trace export success, saw health={health:?}"
        );
        assert!(
            health.export_latency_ms_traces > 0.0,
            "expected trace export latency, saw health={health:?}"
        );
    }
    if expect_metrics {
        assert_eq!(
            health.export_failures_metrics, 0,
            "expected metric export success, saw health={health:?}"
        );
        assert!(
            health.export_latency_ms_metrics > 0.0,
            "expected metric export latency, saw health={health:?}"
        );
    }
}

fn export_health_observed(
    health: &HealthSnapshot,
    expect_logs: bool,
    expect_traces: bool,
    expect_metrics: bool,
) -> bool {
    signal_observed(expect_logs, health.export_latency_ms_logs, health.export_failures_logs)
        && signal_observed(
            expect_traces,
            health.export_latency_ms_traces,
            health.export_failures_traces,
        )
        && signal_observed(
            expect_metrics,
            health.export_latency_ms_metrics,
            health.export_failures_metrics,
        )
}

fn signal_observed(expected: bool, latency_ms: f64, failures: u64) -> bool {
    !expected || latency_ms > 0.0 || failures > 0
}

#[test]
fn otlp_runtime_exports_logs_only_to_http_endpoint() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let health = run_runtime_otlp_smoke(false, false);
    assert_export_health_success(&health, true, false, false);
}

#[test]
fn otlp_runtime_exports_logs_and_traces_to_http_endpoint() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let health = run_runtime_otlp_smoke(true, false);
    assert_export_health_success(&health, true, true, false);
}

#[test]
fn otlp_runtime_exports_all_signals_to_http_endpoint() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    let health = run_runtime_otlp_smoke(true, true);
    assert_export_health_success(&health, true, true, true);
}
