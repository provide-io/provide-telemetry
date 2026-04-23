// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

#![cfg(feature = "otel")]

use std::env;
use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use provide_telemetry::testing::{acquire_test_state_lock, reset_telemetry_state};
use provide_telemetry::{counter, gauge, histogram, setup_telemetry, shutdown_telemetry};

const ENV_KEYS: &[&str] = &[
    "PROVIDE_TELEMETRY_SERVICE_NAME",
    "PROVIDE_METRICS_ENABLED",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
    "OTEL_METRIC_EXPORT_INTERVAL",
];

#[derive(Clone, Debug, PartialEq, Eq)]
struct ObservedRequest {
    path: String,
    body: Vec<u8>,
}

struct MockMetricsCollector {
    endpoint: String,
    seen_requests: Arc<Mutex<Vec<ObservedRequest>>>,
    stopping: Arc<AtomicBool>,
    wake_addr: String,
    worker: Option<thread::JoinHandle<()>>,
}

impl MockMetricsCollector {
    fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind metrics mock collector");
        listener
            .set_nonblocking(true)
            .expect("set metrics mock collector nonblocking");
        let addr = listener.local_addr().expect("collector local addr");
        let seen_requests = Arc::new(Mutex::new(Vec::new()));
        let stopping = Arc::new(AtomicBool::new(false));
        let worker_requests = Arc::clone(&seen_requests);
        let worker_stopping = Arc::clone(&stopping);
        let wake_addr = addr.to_string();

        let worker = thread::spawn(move || {
            while !worker_stopping.load(Ordering::Relaxed) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        if let Some(request) = read_request(&mut stream) {
                            worker_requests
                                .lock()
                                .expect("seen_requests lock poisoned")
                                .push(request);
                        }
                        let _ = stream.write_all(
                            b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                        );
                        let _ = stream.flush();
                    }
                    Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(10));
                    }
                    Err(err) => panic!("metrics mock collector accept failed: {err}"),
                }
            }
        });

        Self {
            endpoint: format!("http://{addr}"),
            seen_requests,
            stopping,
            wake_addr,
            worker: Some(worker),
        }
    }

    fn wait_for_metric_name(&self, expected: &str, timeout: Duration) -> Vec<ObservedRequest> {
        let deadline = Instant::now() + timeout;
        loop {
            let seen = self.requests();
            if seen
                .iter()
                .any(|request| request_contains_metric_name(request, expected))
            {
                return seen;
            }
            if Instant::now() >= deadline {
                return seen;
            }
            thread::sleep(Duration::from_millis(25));
        }
    }

    fn requests(&self) -> Vec<ObservedRequest> {
        self.seen_requests
            .lock()
            .expect("seen_requests lock poisoned")
            .clone()
    }
}

impl Drop for MockMetricsCollector {
    fn drop(&mut self) {
        self.stopping.store(true, Ordering::Relaxed);
        if let Ok(stream) = TcpStream::connect(&self.wake_addr) {
            let _ = stream.shutdown(Shutdown::Both);
        }
        if let Some(worker) = self.worker.take() {
            worker.join().expect("metrics mock collector thread");
        }
    }
}

fn read_request(stream: &mut TcpStream) -> Option<ObservedRequest> {
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .expect("metrics mock collector read timeout");
    let mut buf = Vec::new();
    let mut chunk = [0_u8; 4096];
    let mut header_end = None;
    while header_end.is_none() {
        let read = stream.read(&mut chunk).ok()?;
        if read == 0 {
            return None;
        }
        buf.extend_from_slice(&chunk[..read]);
        header_end = buf.windows(4).position(|window| window == b"\r\n\r\n");
    }
    let header_end = buf
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|pos| pos + 4)?;
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
    let mut body = buf[header_end..].to_vec();
    while body.len() < content_length {
        let read = stream.read(&mut chunk).ok()?;
        if read == 0 {
            return None;
        }
        body.extend_from_slice(&chunk[..read]);
    }
    body.truncate(content_length);
    Some(ObservedRequest { path, body })
}

fn request_contains_metric_name(request: &ObservedRequest, expected: &str) -> bool {
    request.path == "/v1/metrics"
        && request
            .body
            .windows(expected.len())
            .any(|window| window == expected.as_bytes())
}

fn request_debug_summary(requests: &[ObservedRequest]) -> Vec<(String, String)> {
    requests
        .iter()
        .map(|request| {
            (
                request.path.clone(),
                String::from_utf8_lossy(&request.body).into_owned(),
            )
        })
        .collect()
}

fn with_metrics_env(endpoint: &str, test: impl FnOnce()) {
    let mut snapshot = Vec::with_capacity(ENV_KEYS.len());
    for key in ENV_KEYS {
        snapshot.push(((*key).to_string(), env::var(key).ok()));
    }

    // SAFETY: tests are serialized with acquire_test_state_lock at call sites.
    unsafe {
        for key in ENV_KEYS {
            env::remove_var(key);
        }
        env::set_var(
            "PROVIDE_TELEMETRY_SERVICE_NAME",
            "provide-telemetry-metrics-test",
        );
        env::set_var("PROVIDE_METRICS_ENABLED", "true");
        env::set_var(
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
            format!("{endpoint}/v1/metrics"),
        );
        env::set_var("OTEL_EXPORTER_OTLP_METRICS_PROTOCOL", "http/json");
        env::set_var("OTEL_METRIC_EXPORT_INTERVAL", "60000");
    }

    test();

    // SAFETY: tests are serialized with acquire_test_state_lock at call sites.
    unsafe {
        for (key, value) in snapshot {
            match value {
                Some(value) => env::set_var(key, value),
                None => env::remove_var(key),
            }
        }
    }
}

fn run_metrics_export_smoke(expected_metric_name: &str, test: impl FnOnce()) {
    let collector = MockMetricsCollector::start();
    with_metrics_env(&collector.endpoint, || {
        setup_telemetry().expect("setup_telemetry should succeed");
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(test));
        shutdown_telemetry().expect("shutdown_telemetry should succeed");
        result.expect("metric export smoke test should not panic");
    });

    let seen = collector.wait_for_metric_name(expected_metric_name, Duration::from_secs(1));
    assert!(
        seen.iter()
            .any(|request| request_contains_metric_name(request, expected_metric_name)),
        "expected OTLP metrics export for {expected_metric_name}, saw requests={:?}",
        request_debug_summary(&seen)
    );
    reset_telemetry_state();
}

#[test]
fn metrics_otel_counter_add_exports_when_provider_is_installed() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    run_metrics_export_smoke("metrics.otel.counter", || {
        let metric = counter("metrics.otel.counter", None, None);
        metric.add(1.0, None);
        assert_eq!(metric.value(), 1.0);
    });
}

#[test]
fn metrics_otel_gauge_set_exports_when_provider_is_installed() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    run_metrics_export_smoke("metrics.otel.gauge", || {
        let metric = gauge("metrics.otel.gauge", None, None);
        metric.set(7.0, None);
        assert_eq!(metric.value(), 7.0);
    });
}

#[test]
fn metrics_otel_histogram_record_exports_when_provider_is_installed() {
    let _guard = acquire_test_state_lock();
    reset_telemetry_state();

    run_metrics_export_smoke("metrics.otel.histogram", || {
        let metric = histogram("metrics.otel.histogram", None, None);
        metric.record(3.0, None);
        assert_eq!(metric.count(), 1);
        assert_eq!(metric.total(), 3.0);
    });
}
