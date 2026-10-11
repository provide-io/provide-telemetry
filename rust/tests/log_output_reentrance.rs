// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// A `set_log_output` writer that logs back through the SDK.
//
// `log_output` in spec/telemetry-api.yaml: a record logged from inside the log
// output writer, on the call stack already writing to it, is not written and
// counts as an export failure; concurrent writers are never dropped.
//
// Before the guard, a writer that logged from inside `write` deadlocked: the
// render path held its capture mutex across the call to the writer, and the
// sink held its own, and the nested record asked the same thread for both. A
// writer that returned an error or panicked lost its record without a count,
// and a panic unwound out of the caller's log call.

use std::io::{self, Write};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use provide_telemetry::testing::acquire_test_state_lock;
use provide_telemetry::{
    clear_log_output, configure_logging, get_health_snapshot, reset_logging_config_for_tests,
    set_log_output, shutdown_telemetry, Logger, LoggingConfig,
};

static SINK_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

fn sink_lock() -> &'static Mutex<()> {
    SINK_LOCK.get_or_init(|| Mutex::new(()))
}

fn emit(message: &str) {
    Logger::new(Some("reentrance.test")).info(message);
}

/// Run `f` on its own thread and fail if it has not returned within a few
/// seconds — the visible form of a deadlock, rather than a hung suite.
fn within_deadline<F: FnOnce() + Send + 'static>(f: F) {
    let (done, finished) = mpsc::channel();
    std::thread::spawn(move || {
        f();
        let _ = done.send(());
    });
    finished
        .recv_timeout(Duration::from_secs(10))
        .expect("deadlocked: the call did not return");
}

/// What the writer does from inside `write` or `flush`.
#[derive(Clone, Copy, PartialEq)]
enum Nested {
    Nothing,
    Log,
    Fail,
    Panic,
}

#[derive(Clone)]
struct CallbackWriter {
    buf: Arc<Mutex<Vec<u8>>>,
    on_write: Nested,
    on_flush: Nested,
    flushes: Arc<AtomicUsize>,
}

impl CallbackWriter {
    fn new(on_write: Nested, on_flush: Nested) -> Self {
        Self {
            buf: Arc::default(),
            on_write,
            on_flush,
            flushes: Arc::default(),
        }
    }

    fn contents(&self) -> String {
        String::from_utf8_lossy(&self.buf.lock().expect("buf")).to_string()
    }
}

fn act(nested: Nested, what: &str) -> io::Result<()> {
    match nested {
        Nested::Nothing => Ok(()),
        Nested::Log => {
            Logger::new(Some("writer")).error(what);
            Ok(())
        }
        Nested::Fail => Err(io::Error::new(io::ErrorKind::BrokenPipe, what.to_string())),
        Nested::Panic => panic!("{what}"),
    }
}

impl Write for CallbackWriter {
    fn write(&mut self, data: &[u8]) -> io::Result<usize> {
        act(self.on_write, "writer.reports.trouble")?;
        self.buf.lock().expect("buf").extend_from_slice(data);
        Ok(data.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        self.flushes.fetch_add(1, Ordering::SeqCst);
        act(self.on_flush, "flush.reports.trouble")
    }
}

fn configure(fmt: &str) {
    reset_logging_config_for_tests();
    configure_logging(LoggingConfig {
        level: "DEBUG".to_string(),
        fmt: fmt.to_string(),
        include_timestamp: false,
        ..Default::default()
    });
}

#[test]
fn a_writer_that_logs_back_is_refused_not_deadlocked() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().unwrap_or_else(|e| e.into_inner());

    for fmt in ["json", "console", "pretty"] {
        configure(fmt);
        let writer = CallbackWriter::new(Nested::Log, Nested::Nothing);
        set_log_output(writer.clone());
        let before = get_health_snapshot();

        within_deadline(|| {
            emit("outer.record");
            emit("second.record");
        });

        let after = get_health_snapshot();
        clear_log_output();
        assert_eq!(
            after.export_failures_logs - before.export_failures_logs,
            2,
            "{fmt}: one export failure per nested record"
        );
        assert_eq!(after.emitted_logs - before.emitted_logs, 4, "{fmt}");
        let written = writer.contents();
        assert!(written.contains("outer.record"), "{fmt}: {written:?}");
        assert!(written.contains("second.record"), "{fmt}: {written:?}");
        assert!(
            !written.contains("writer.reports.trouble"),
            "{fmt}: {written:?}"
        );
    }
}

#[test]
fn a_writer_that_logs_from_its_flush_at_shutdown_does_not_deadlock() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().unwrap_or_else(|e| e.into_inner());

    configure("json");
    let writer = CallbackWriter::new(Nested::Nothing, Nested::Log);
    set_log_output(writer.clone());
    emit("outer.record");

    within_deadline(|| shutdown_telemetry(Some(1.0)).expect("shutdown"));

    assert_eq!(writer.flushes.load(Ordering::SeqCst), 1);
    assert!(writer.contents().contains("outer.record"));
    assert!(!writer.contents().contains("flush.reports.trouble"));
}

#[test]
fn a_writer_that_fails_or_panics_costs_only_its_record_and_is_counted() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().unwrap_or_else(|e| e.into_inner());

    for nested in [Nested::Fail, Nested::Panic] {
        configure("json");
        set_log_output(CallbackWriter::new(nested, Nested::Nothing));
        let before = get_health_snapshot();

        within_deadline(|| emit("lost.record"));

        let after = get_health_snapshot();
        assert_eq!(after.export_failures_logs - before.export_failures_logs, 1);
        assert_eq!(after.emitted_logs - before.emitted_logs, 1);

        // The sink is still usable afterwards: the lock was released, and a
        // panic did not leave the thread marked as inside the writer.
        let healthy = CallbackWriter::new(Nested::Nothing, Nested::Nothing);
        set_log_output(healthy.clone());
        emit("after.failure");
        clear_log_output();
        assert!(healthy.contents().contains("after.failure"));
    }
}

#[test]
fn a_flush_that_panics_does_not_abort_shutdown() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().unwrap_or_else(|e| e.into_inner());

    configure("json");
    set_log_output(CallbackWriter::new(Nested::Nothing, Nested::Panic));

    within_deadline(|| shutdown_telemetry(Some(1.0)).expect("shutdown"));
}

/// A writer whose `Drop` logs, as a buffered writer reporting a failed final
/// flush might. Replacing or clearing it must not deadlock on the slot.
struct LogsOnDrop(Arc<AtomicBool>);

impl Write for LogsOnDrop {
    fn write(&mut self, data: &[u8]) -> io::Result<usize> {
        Ok(data.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

impl Drop for LogsOnDrop {
    fn drop(&mut self) {
        emit("dropped.writer.reports");
        self.0.store(true, Ordering::SeqCst);
    }
}

#[test]
fn a_writer_that_logs_from_its_drop_is_released_without_deadlock() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().unwrap_or_else(|e| e.into_inner());

    configure("json");
    let dropped = Arc::new(AtomicBool::new(false));
    set_log_output(LogsOnDrop(Arc::clone(&dropped)));
    let next = CallbackWriter::new(Nested::Nothing, Nested::Nothing);
    let replacement = next.clone();
    within_deadline(move || set_log_output(replacement));
    assert!(dropped.load(Ordering::SeqCst));
    // The old writer's last record went to the writer installed in its place.
    assert!(next.contents().contains("dropped.writer.reports"));

    let dropped = Arc::new(AtomicBool::new(false));
    set_log_output(LogsOnDrop(Arc::clone(&dropped)));
    within_deadline(clear_log_output);
    assert!(dropped.load(Ordering::SeqCst));
}

/// Widens the window in which a write is in progress and asserts the sink
/// serialised: two writes inside it at once is a failure.
#[derive(Clone, Default)]
struct SlowWriter {
    busy: Arc<AtomicBool>,
    overlapped: Arc<AtomicBool>,
    lines: Arc<AtomicUsize>,
}

impl Write for SlowWriter {
    fn write(&mut self, data: &[u8]) -> io::Result<usize> {
        if self.busy.swap(true, Ordering::SeqCst) {
            self.overlapped.store(true, Ordering::SeqCst);
        }
        std::thread::yield_now();
        self.lines.fetch_add(1, Ordering::SeqCst);
        self.busy.store(false, Ordering::SeqCst);
        Ok(data.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[test]
fn concurrent_writers_wait_and_are_never_dropped() {
    let _state = acquire_test_state_lock();
    let _sink = sink_lock().lock().unwrap_or_else(|e| e.into_inner());

    configure("json");
    let writer = SlowWriter::default();
    set_log_output(writer.clone());
    let before = get_health_snapshot();

    within_deadline(|| {
        std::thread::scope(|scope| {
            for _ in 0..8 {
                scope.spawn(|| {
                    for _ in 0..50 {
                        emit("concurrent.record");
                    }
                });
            }
        });
    });
    clear_log_output();

    let after = get_health_snapshot();
    assert_eq!(after.export_failures_logs - before.export_failures_logs, 0);
    assert_eq!(writer.lines.load(Ordering::SeqCst), 8 * 50);
    assert!(!writer.overlapped.load(Ordering::SeqCst));
}
