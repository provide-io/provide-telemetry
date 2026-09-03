// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// The log output sink: where rendered records go when a host supplies a writer.
//
// Rust is one of the two runtimes a host cannot redirect from outside — emit
// wrote to stderr through `eprintln!` and nothing could intercept it — so the
// crate owes a sink the way Go does. See `log_output` in spec/telemetry-api.yaml.

use std::io::{self, Write};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};

use provide_telemetry::testing::acquire_test_state_lock;
use provide_telemetry::{
    clear_log_output, configure_logging, reset_logging_config_for_tests, set_log_output,
    shutdown_telemetry, Logger, LoggingConfig,
};

/// Emit one record through the crate's own logger, rather than the `log`
/// facade, which only reaches this crate once it is installed globally.
fn emit(message: &str) {
    Logger::new(Some("sink.test")).info(message);
}

/// Serialises the tests in this file: the sink is process-global, and the test
/// harness runs a binary's tests on parallel threads.
static SINK_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn sink_lock() -> &'static Mutex<()> {
    SINK_LOCK.get_or_init(|| Mutex::new(()))
}

/// A writer the test can read back, and that the SDK can own at the same time.
#[derive(Clone, Default)]
struct SharedBuf(Arc<Mutex<Vec<u8>>>);

impl SharedBuf {
    fn contents(&self) -> String {
        String::from_utf8_lossy(&self.0.lock().expect("buf")).to_string()
    }
}

impl Write for SharedBuf {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.0.lock().expect("buf").extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

/// Counts flushes, so a test can tell a flush that happened from one that was
/// merely promised.
#[derive(Clone, Default)]
struct FlushCounter(Arc<AtomicUsize>);

impl Write for FlushCounter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        self.0.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

fn logging(fmt: &str) -> LoggingConfig {
    LoggingConfig {
        level: "DEBUG".to_string(),
        fmt: fmt.to_string(),
        include_timestamp: false,
        ..Default::default()
    }
}

fn emit_one(fmt: &str, message: &str) -> SharedBuf {
    reset_logging_config_for_tests();
    configure_logging(logging(fmt));
    let buf = SharedBuf::default();
    set_log_output(buf.clone());
    emit(message);
    buf
}

#[test]
fn json_records_reach_an_installed_writer() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().expect("sink lock");

    let buf = emit_one("json", "to-the-sink");
    clear_log_output();

    let written = buf.contents();
    assert!(
        written.contains("to-the-sink"),
        "the record never reached the writer: {written:?}"
    );
    assert!(written.ends_with('\n'), "a record is written as a line");
}

#[test]
fn console_records_reach_an_installed_writer() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().expect("sink lock");

    let buf = emit_one("console", "console-to-the-sink");
    clear_log_output();

    assert!(buf.contents().contains("console-to-the-sink"));
}

#[test]
fn pretty_records_reach_an_installed_writer_without_colour() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().expect("sink lock");

    let buf = emit_one("pretty", "pretty-to-the-sink");
    clear_log_output();

    let written = buf.contents();
    assert!(written.contains("pretty-to-the-sink"));
    assert!(
        !written.contains('\u{1b}'),
        "ANSI escapes were written to a destination not known to render them: {written:?}"
    );
}

#[test]
fn clearing_the_output_stops_writing_to_it() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().expect("sink lock");

    let buf = emit_one("json", "before-clear");
    clear_log_output();
    emit("after-clear");

    let written = buf.contents();
    assert!(written.contains("before-clear"));
    assert!(
        !written.contains("after-clear"),
        "records kept arriving after the writer was cleared: {written:?}"
    );
}

#[test]
fn a_second_writer_replaces_the_first() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().expect("sink lock");

    let first = emit_one("json", "for-the-first");
    let second = SharedBuf::default();
    set_log_output(second.clone());
    emit("for-the-second");
    clear_log_output();

    assert!(first.contents().contains("for-the-first"));
    assert!(
        !first.contents().contains("for-the-second"),
        "the replaced writer kept receiving records"
    );
    assert!(second.contents().contains("for-the-second"));
}

#[test]
fn records_arrive_whole_under_concurrent_writers() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().expect("sink lock");

    reset_logging_config_for_tests();
    configure_logging(logging("json"));
    let buf = SharedBuf::default();
    set_log_output(buf.clone());

    std::thread::scope(|scope| {
        for worker in 0..4 {
            scope.spawn(move || {
                for n in 0..10 {
                    emit(&format!("worker-{worker}-record-{n}"));
                }
            });
        }
    });
    clear_log_output();

    let written = buf.contents();
    let lines: Vec<&str> = written.lines().collect();
    assert_eq!(lines.len(), 40, "expected one line per record: {written:?}");
    for line in lines {
        assert!(
            serde_json::from_str::<serde_json::Value>(line).is_ok(),
            "a record was interleaved with another: {line:?}"
        );
    }
}

#[test]
fn shutdown_flushes_and_releases_the_writer() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().expect("sink lock");

    let buf = emit_one("json", "before-shutdown");
    shutdown_telemetry(Some(1.0)).expect("shutdown");
    emit("after-shutdown");

    let written = buf.contents();
    assert!(written.contains("before-shutdown"));
    assert!(
        !written.contains("after-shutdown"),
        "shutdown left the host's writer installed: {written:?}"
    );
}

#[test]
fn the_writer_survives_a_logging_reconfiguration() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().expect("sink lock");

    let buf = emit_one("json", "before-reconfigure");
    configure_logging(logging("console"));
    emit("after-reconfigure");
    clear_log_output();

    let written = buf.contents();
    assert!(written.contains("before-reconfigure"));
    assert!(
        written.contains("after-reconfigure"),
        "reconfiguring logging dropped the host's writer: {written:?}"
    );
}

// A buffered writer holds its tail, and shutdown is the last moment a host can
// expect its records to have landed — so shutdown flushes before it lets go.
#[test]
fn shutdown_flushes_the_writer_it_releases() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().expect("sink lock");

    reset_logging_config_for_tests();
    configure_logging(logging("json"));
    let counter = FlushCounter::default();
    set_log_output(counter.clone());
    emit("before-flush");

    let before = counter.0.load(Ordering::SeqCst);
    shutdown_telemetry(Some(1.0)).expect("shutdown");

    assert!(
        counter.0.load(Ordering::SeqCst) > before,
        "shutdown released the writer without flushing it"
    );
}
