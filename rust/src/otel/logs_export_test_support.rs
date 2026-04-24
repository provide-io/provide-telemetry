use super::*;

use std::io::{Read, Write};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use crate::health::{get_health_snapshot, HealthSnapshot};
use crate::runtime::set_active_config;
use crate::testing::reset_telemetry_state;

const MOCK_COLLECTOR_READ_TIMEOUT: Duration = Duration::from_secs(10);

pub(super) struct MockOtlpCollector {
    pub(super) endpoint: String,
    seen_paths: Arc<Mutex<Vec<String>>>,
    stopping: Arc<AtomicBool>,
    wake_addr: String,
    worker: Option<thread::JoinHandle<()>>,
}

impl MockOtlpCollector {
    pub(super) fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind OTLP mock collector");
        listener
            .set_nonblocking(true)
            .expect("set OTLP mock collector nonblocking");
        let addr = listener.local_addr().expect("mock collector local addr");
        let seen_paths = Arc::new(Mutex::new(Vec::new()));
        let stopping = Arc::new(AtomicBool::new(false));
        let worker_paths = Arc::clone(&seen_paths);
        let worker_stopping = Arc::clone(&stopping);
        let wake_addr = addr.to_string();

        let worker = thread::spawn(move || {
            while !worker_stopping.load(Ordering::Relaxed) {
                handle_accept_result(listener.accept(), &worker_paths);
            }
        });

        Self {
            endpoint: format!("http://{addr}"),
            seen_paths,
            stopping,
            wake_addr,
            worker: Some(worker),
        }
    }

    pub(super) fn wait_for_path(&self, expected: &str, timeout: Duration) -> Vec<String> {
        let deadline = Instant::now() + timeout;
        loop {
            let seen = self.paths();
            if seen.iter().any(|path| path == expected) {
                return seen;
            }
            if Instant::now() >= deadline {
                return seen;
            }
            thread::sleep(Duration::from_millis(25));
        }
    }

    pub(super) fn wait_for_all(&self, expected: &[&str], timeout: Duration) -> Vec<String> {
        let deadline = Instant::now() + timeout;
        loop {
            let seen = self.paths();
            if expected
                .iter()
                .all(|path| seen.iter().any(|seen_path| seen_path == path))
            {
                return seen;
            }
            if Instant::now() >= deadline {
                return seen;
            }
            thread::sleep(Duration::from_millis(25));
        }
    }

    pub(super) fn paths(&self) -> Vec<String> {
        self.seen_paths
            .lock()
            .expect("OTLP mock seen_paths lock poisoned")
            .clone()
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

pub(super) fn export_test_config(endpoint: &str) -> TelemetryConfig {
    let mut cfg = TelemetryConfig {
        service_name: "test".to_string(),
        ..TelemetryConfig::default()
    };
    cfg.logging.otlp_endpoint = Some(format!("{endpoint}/v1/logs"));
    cfg
}

pub(super) fn reset_all_otel_state() {
    reset_telemetry_state();
    shutdown_logger_provider();
    super::super::metrics::shutdown_meter_provider();
    super::super::traces::shutdown_tracer_provider();
    set_active_config(None);
}

pub(super) fn wait_for_export_health(
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
        thread::sleep(Duration::from_millis(25));
    }
}

pub(super) fn assert_export_health_success(
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

pub(super) fn export_health_success(
    health: &HealthSnapshot,
    expect_logs: bool,
    expect_traces: bool,
    expect_metrics: bool,
) -> bool {
    (!expect_logs || (health.export_failures_logs == 0 && health.export_latency_ms_logs > 0.0))
        && (!expect_traces
            || (health.export_failures_traces == 0 && health.export_latency_ms_traces > 0.0))
        && (!expect_metrics
            || (health.export_failures_metrics == 0 && health.export_latency_ms_metrics > 0.0))
}

pub(super) fn settle_otel_exports() {
    thread::sleep(Duration::from_millis(200));
}

fn export_health_observed(
    health: &HealthSnapshot,
    expect_logs: bool,
    expect_traces: bool,
    expect_metrics: bool,
) -> bool {
    signal_observed(
        expect_logs,
        health.export_latency_ms_logs,
        health.export_failures_logs,
    ) && signal_observed(
        expect_traces,
        health.export_latency_ms_traces,
        health.export_failures_traces,
    ) && signal_observed(
        expect_metrics,
        health.export_latency_ms_metrics,
        health.export_failures_metrics,
    )
}

fn signal_observed(expected: bool, latency_ms: f64, failures: u64) -> bool {
    !expected || latency_ms > 0.0 || failures > 0
}

fn read_request_path(stream: &mut TcpStream) -> Option<String> {
    stream
        .set_read_timeout(Some(MOCK_COLLECTOR_READ_TIMEOUT))
        .expect("mock collector read timeout");
    let mut buf = Vec::new();
    let mut chunk = [0_u8; 4096];
    let mut header_end = None;
    while header_end.is_none() {
        let read = match stream.read(&mut chunk) {
            Ok(read) => read,
            Err(_) => return None,
        };
        if read == 0 {
            return None;
        }
        buf.extend_from_slice(&chunk[..read]);
        header_end = buf
            .windows(4)
            .position(|window| window == b"\r\n\r\n")
            .map(|pos| pos + 4);
    }
    let header_end = header_end.expect("header end must be set before leaving loop");

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
    let mut remaining = content_length.saturating_sub(buf.len().saturating_sub(header_end));
    while remaining > 0 {
        let read = match stream.read(&mut chunk) {
            Ok(read) => read,
            Err(_) => return None,
        };
        if read == 0 {
            return None;
        }
        remaining = remaining.saturating_sub(read);
    }
    Some(path)
}

fn handle_accept_result(
    result: std::io::Result<(TcpStream, std::net::SocketAddr)>,
    worker_paths: &Arc<Mutex<Vec<String>>>,
) {
    match result {
        Ok((mut stream, _)) => {
            if let Some(path) = read_request_path(&mut stream) {
                worker_paths
                    .lock()
                    .expect("OTLP mock seen_paths lock poisoned")
                    .push(path);
            }
            let _ = stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
            let _ = stream.flush();
        }
        Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {
            thread::sleep(Duration::from_millis(10));
        }
        Err(err) => panic!("mock collector accept failed: {err}"),
    }
}

#[cfg(test)]
#[path = "logs_export_test_support/tests.rs"]
mod tests;
