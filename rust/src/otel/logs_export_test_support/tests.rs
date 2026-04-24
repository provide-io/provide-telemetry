use super::*;

use std::io::ErrorKind;
use std::panic::{self, AssertUnwindSafe};

use crate::testing::acquire_test_state_lock;

fn read_request_with_writer<F, G>(before_read: F, writer_fn: G) -> Option<String>
where
    F: FnOnce(&mut TcpStream),
    G: FnOnce(TcpStream) + Send + 'static,
{
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind request reader listener");
    let addr = listener.local_addr().expect("request reader local addr");
    let writer =
        thread::spawn(move || writer_fn(TcpStream::connect(addr).expect("connect request reader")));

    let (mut stream, _) = listener.accept().expect("accept request reader");
    before_read(&mut stream);
    let parsed = read_request_path(&mut stream);
    writer.join().expect("request writer thread");
    parsed
}

fn read_request_bytes(bytes: Option<&[u8]>) -> Option<String> {
    let payload = bytes.map(Vec::from);
    read_request_with_writer(
        |_| {},
        move |mut client| {
            if let Some(payload) = payload {
                client
                    .write_all(&payload)
                    .expect("write request payload to request reader");
                client
                    .flush()
                    .expect("flush request payload to request reader");
            }
            client
                .shutdown(Shutdown::Write)
                .expect("shutdown request writer");
        },
    )
}

#[test]
fn export_test_support_wait_helpers_cover_timeout_paths() {
    let _guard = acquire_test_state_lock();
    reset_all_otel_state();
    let collector = MockOtlpCollector::start();

    assert!(collector
        .wait_for_path("/missing", Duration::from_millis(10))
        .is_empty());
    assert!(collector
        .wait_for_all(&["/v1/logs", "/v1/traces"], Duration::from_millis(10))
        .is_empty());
    collector
        .seen_paths
        .lock()
        .expect("seen paths lock poisoned")
        .extend(["/v1/logs".to_string(), "/v1/traces".to_string()]);
    assert_eq!(
        collector.wait_for_all(&["/v1/logs", "/v1/traces"], Duration::from_millis(10)),
        vec!["/v1/logs".to_string(), "/v1/traces".to_string()]
    );

    let timed_out = wait_for_export_health(true, false, false, Duration::from_millis(1));
    assert_eq!(
        timed_out,
        HealthSnapshot {
            circuit_state_logs: "closed".to_string(),
            circuit_state_traces: "closed".to_string(),
            circuit_state_metrics: "closed".to_string(),
            ..HealthSnapshot::default()
        }
    );
}

#[test]
fn export_test_support_health_assertions_cover_all_signals() {
    let _guard = acquire_test_state_lock();
    reset_all_otel_state();
    let mut health = HealthSnapshot {
        export_latency_ms_logs: 1.0,
        export_latency_ms_traces: 2.0,
        export_latency_ms_metrics: 3.0,
        ..HealthSnapshot::default()
    };

    assert!(signal_observed(false, 0.0, 0));
    assert!(!signal_observed(true, 0.0, 0));
    assert!(signal_observed(true, 1.0, 0));
    assert!(signal_observed(true, 0.0, 1));
    assert!(export_health_success(&health, true, true, true));
    assert_export_health_success(&health, true, true, true);
    assert!(export_health_observed(&health, true, true, true));

    health.export_failures_metrics = 1;
    health.export_latency_ms_metrics = 0.0;
    assert!(export_health_observed(&health, false, false, true));
    assert!(!export_health_success(&health, false, false, true));
    let panic = panic::catch_unwind(AssertUnwindSafe(|| {
        assert_export_health_success(&health, false, false, true);
    }));
    assert!(
        panic.is_err(),
        "metric assertion should fail when only failures are present"
    );
}

#[test]
fn export_test_support_handles_connection_edge_cases() {
    let worker_paths = Arc::new(Mutex::new(Vec::new()));
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind accept helper listener");
    let addr = listener.local_addr().expect("accept helper local addr");
    let closer = thread::spawn(move || {
        let stream = TcpStream::connect(addr).expect("connect accept helper");
        stream
            .shutdown(Shutdown::Write)
            .expect("shutdown accept helper writer");
    });
    let accepted = listener.accept().expect("accept helper connection");
    handle_accept_result(Ok(accepted), &worker_paths);
    closer.join().expect("accept helper closer");
    assert!(worker_paths
        .lock()
        .expect("accept helper lock poisoned")
        .is_empty());

    handle_accept_result(
        Err(std::io::Error::new(ErrorKind::WouldBlock, "retry")),
        &worker_paths,
    );

    let panic = panic::catch_unwind(AssertUnwindSafe(|| {
        handle_accept_result(
            Err(std::io::Error::other("collector accept boom")),
            &worker_paths,
        );
    }));
    assert!(
        panic.is_err(),
        "unexpected accept errors should still panic"
    );
}

#[test]
fn export_test_support_drop_tolerates_failed_wake_connection() {
    let collector = MockOtlpCollector {
        endpoint: "http://127.0.0.1:0".to_string(),
        seen_paths: Arc::new(Mutex::new(Vec::new())),
        stopping: Arc::new(AtomicBool::new(false)),
        wake_addr: "127.0.0.1:1".to_string(),
        worker: None,
    };

    drop(collector);
}

#[test]
fn export_test_support_drop_still_joins_worker_without_wake_connection() {
    let _guard = acquire_test_state_lock();
    reset_all_otel_state();
    let mut collector = MockOtlpCollector::start();
    collector.wake_addr = "127.0.0.1:1".to_string();

    drop(collector);
}

#[test]
fn export_test_support_read_request_path_handles_invalid_inputs() {
    assert_eq!(read_request_bytes(None), None);
    assert_eq!(
        read_request_bytes(Some(b"\xff /v1/logs HTTP/1.1\r\nContent-Length: 0\r\n\r\n")),
        None
    );
    assert_eq!(
        read_request_bytes(Some(b"INVALID\r\nContent-Length: 0\r\n\r\n")),
        None
    );
    assert_eq!(
        read_request_bytes(Some(b"POST /v1/logs HTTP/1.1\r\nContent-Length: 5\r\n\r\n")),
        None
    );
    assert_eq!(
        read_request_bytes(Some(b"POST /v1/logs HTTP/1.1\r\nContent-Length: 0\r\n\r\n")),
        Some("/v1/logs".to_string())
    );
    assert_eq!(
        read_request_with_writer(
            |stream| stream
                .set_nonblocking(true)
                .expect("set nonblocking request reader"),
            |client| {
                thread::sleep(Duration::from_millis(25));
                drop(client);
            }
        ),
        None
    );
    assert_eq!(
        read_request_with_writer(
            |stream| stream
                .set_nonblocking(true)
                .expect("set nonblocking request reader"),
            |mut client| {
                client
                    .write_all(b"POST /v1/logs HTTP/1.1\r\nContent-Length: 5\r\n\r\n")
                    .expect("write partial body request headers");
                client.flush().expect("flush partial body request headers");
                thread::sleep(Duration::from_millis(25));
            }
        ),
        None
    );
    assert_eq!(
        read_request_with_writer(
            |_| {},
            |mut client| {
                client
                    .write_all(b"POST /v1/logs HTTP/1.1\r\nContent-Length: 5\r\n\r\n")
                    .expect("write request headers to request reader");
                client
                    .flush()
                    .expect("flush request headers to request reader");
                thread::sleep(Duration::from_millis(25));
                client
                    .write_all(b"hello")
                    .expect("write request body to request reader");
                client
                    .flush()
                    .expect("flush request body to request reader");
                client
                    .shutdown(Shutdown::Write)
                    .expect("shutdown segmented request writer");
            }
        ),
        Some("/v1/logs".to_string())
    );
    assert_eq!(
        read_request_with_writer(
            |stream| stream
                .set_nonblocking(true)
                .expect("set nonblocking request reader"),
            |mut client| {
                client
                    .write_all(b"POST /v1/logs HTTP/1.1\r\nContent-Length: 5\r\n\r\n")
                    .expect("write truncated request headers");
                client.flush().expect("flush truncated request headers");
                thread::sleep(Duration::from_millis(250));
            }
        ),
        None
    );
}
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
