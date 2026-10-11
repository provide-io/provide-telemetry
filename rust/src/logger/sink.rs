// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Where rendered log records go.
//!
//! Emission wrote to stderr through `eprintln!` and nothing could intercept it,
//! which made Rust one of the two runtimes a host cannot redirect from outside
//! — Go being the other, until it gained `WithLogOutput`. A host that runs
//! several language runtimes into one stream needs the writer from every SDK
//! involved, not one of them: without it the combined output cannot be
//! attributed to a runtime, and the Rust side is pushed onto a separate logging
//! stack that produces structurally different telemetry for the same operation.
//!
//! The writer is a handle rather than a string, so no environment variable
//! names it and it is not part of `TelemetryConfig` — the config is a value
//! callers receive by copy and Rust deserialises across a reconfiguration, and
//! a handle survives neither. It is installed and cleared on its own, which
//! also answers a question the Go side leaves open: a reconfiguration does not
//! touch the writer, so a host can change logging config freely without
//! reinstalling it, and can swap or drop the writer without reconfiguring.
//!
//! Colour is off whenever a writer is installed. The invariant the pretty
//! renderer owes is that ANSI never reaches a destination not known to render
//! it, and a `Write` is not something this crate can ask. Go recovers colour by
//! asking a writer that offers `IsTerminal() bool`, which its structural
//! interfaces make free; expressing the same in Rust would cost every host a
//! trait implementation and the ability to pass a plain `File`. The safe answer
//! costs nobody anything, and the default stderr path still probes.
//!
//! The writer is the host's code, run inside a log call, so the sink puts two
//! boundaries around it. A `write` or `flush` that fails or panics costs only
//! the record it was writing, which the logger counts as a log export failure;
//! the panic does not unwind out of the caller's log call. And a writer that
//! logs through this crate from inside its own `write` or `flush` comes back to
//! the sink on the thread holding the sink's lock — where a `std::sync::Mutex`
//! deadlocks — so that nested record is refused instead: not written, and
//! counted the same way. Records from other threads are never refused; they
//! wait for the lock as they always have.

use std::cell::Cell;
use std::io::Write;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{LazyLock, Mutex};

/// The installed writer, if a host supplied one.
static LOG_OUTPUT: LazyLock<Mutex<Option<Box<dyn Write + Send>>>> =
    LazyLock::new(|| Mutex::new(None));

thread_local! {
    /// Set while this thread is inside the host's `write` or `flush`.
    ///
    /// Thread-local because a thread is exactly the unit that can re-enter: a
    /// writer is synchronous, so nothing else runs on its thread until it
    /// returns, while a record from any other thread is a concurrent caller.
    /// One flag for every writer, as Go's stack check is one check for every
    /// sink: a writer that logs into a replacement another thread has just
    /// installed is refused too.
    static INSIDE_WRITER: Cell<bool> = const { Cell::new(false) };
}

/// Why a record did not reach the installed writer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum WriteFailure {
    /// The record was logged from inside the writer, on the thread writing.
    Reentered,
    /// The writer returned an error or panicked.
    Writer,
}

/// Run `f`, a call into the host's writer, with this thread marked as inside
/// it, turning an error or a panic into a failure. The mark is cleared on the
/// way out either way.
fn call_writer(f: impl FnOnce() -> std::io::Result<()>) -> Result<(), WriteFailure> {
    INSIDE_WRITER.with(|inside| inside.set(true));
    let outcome = catch_unwind(AssertUnwindSafe(f));
    INSIDE_WRITER.with(|inside| inside.set(false));
    match outcome {
        Ok(Ok(())) => Ok(()),
        _ => Err(WriteFailure::Writer),
    }
}

/// Whether this thread is running inside the host's writer right now.
fn inside_writer() -> bool {
    INSIDE_WRITER.with(Cell::get)
}

/// Send every rendered log record to `writer` instead of stderr.
///
/// All three formats honour it — `json`, `console` and `pretty`. Writes are
/// serialised, so a record arrives whole even when several threads log at once.
/// Installing a second writer replaces the first; the previous writer is
/// dropped, which flushes it if its `Drop` does.
///
/// Colour is off while a writer is installed: see the module note.
///
/// A record the writer logs through this crate from inside its own `write` or
/// `flush` is not written, and is counted as a log export failure; the record
/// being written is unaffected, and records from other threads still wait
/// their turn and are never dropped. A writer that returns an error or panics
/// costs only the record it was writing, counted the same way.
///
/// The writer is taken by value rather than as a `Box`, so a caller passes a
/// `File`, a `Vec<u8>` or its own type directly.
pub fn set_log_output<W: Write + Send + 'static>(writer: W) {
    let previous = crate::_lock::lock(&LOG_OUTPUT).replace(Box::new(writer));
    // Dropped once the lock is released: a writer whose `Drop` flushes, and
    // reports a failed flush through this crate, would otherwise deadlock.
    drop(previous);
}

/// Send rendered log records back to stderr, dropping any installed writer.
pub fn clear_log_output() {
    let previous = crate::_lock::lock(&LOG_OUTPUT).take();
    drop(previous);
}

/// Whether a host has installed a writer.
///
/// The pretty renderer asks before deciding colour, because a writer is not a
/// destination this crate can establish as a terminal.
///
/// A thread inside the writer already knows the answer, and must not ask the
/// lock it holds: the pretty renderer runs for a nested record before the sink
/// gets the chance to refuse it.
pub(crate) fn log_output_installed() -> bool {
    if inside_writer() {
        return true;
    }
    crate::_lock::lock(&LOG_OUTPUT).is_some()
}

/// Flush the installed writer, if there is one.
///
/// Shutdown calls it, so a flush that fails or panics is absorbed rather than
/// aborting the teardown.
pub(crate) fn flush_log_output() {
    // Before the lock, which this thread holds if it is inside the writer.
    if inside_writer() {
        return;
    }
    if let Some(writer) = crate::_lock::lock(&LOG_OUTPUT).as_mut() {
        let _ = call_writer(|| writer.flush());
    }
}

/// Write one rendered record, as a line.
///
/// The capture buffer comes first so the test seams keep working with a writer
/// installed, then the writer, then stderr. The capture's lock is released
/// before anything else happens, so the sink's lock is the only one held while
/// the host's writer runs. The record and its newline reach the writer in one
/// `write_all`.
///
/// A failure is returned for the caller to count rather than raised: a logger
/// that panics because the host's pipe closed is worse than a lost record.
pub(crate) fn write_line(capture: &Mutex<Option<Vec<u8>>>, line: &str) -> Result<(), WriteFailure> {
    if let Some(buf) = crate::_lock::lock(capture).as_mut() {
        buf.extend_from_slice(line.as_bytes());
        buf.push(b'\n');
        return Ok(());
    }
    // Before the lock, which this thread holds if it is inside the writer.
    if inside_writer() {
        return Err(WriteFailure::Reentered);
    }
    let mut installed = crate::_lock::lock(&LOG_OUTPUT);
    match installed.as_mut() {
        Some(writer) => {
            let mut record = String::with_capacity(line.len() + 1);
            record.push_str(line);
            record.push('\n');
            call_writer(|| writer.write_all(record.as_bytes()))
        }
        None => {
            eprintln!("{line}");
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // A flush reached from inside the writer returns before the lock this
    // thread already holds. Driven by setting the mark directly, with the lock
    // held to stand in for the writer's frame: a flush that took the lock here
    // would never return.
    #[test]
    fn a_flush_from_inside_the_writer_returns_without_locking() {
        let _held = crate::_lock::lock(&LOG_OUTPUT);
        INSIDE_WRITER.with(|inside| inside.set(true));
        flush_log_output();
        INSIDE_WRITER.with(|inside| inside.set(false));
    }
}
