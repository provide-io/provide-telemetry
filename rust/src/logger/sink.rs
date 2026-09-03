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

use std::io::Write;
use std::sync::{LazyLock, Mutex};

/// The installed writer, if a host supplied one.
static LOG_OUTPUT: LazyLock<Mutex<Option<Box<dyn Write + Send>>>> =
    LazyLock::new(|| Mutex::new(None));

/// Send every rendered log record to `writer` instead of stderr.
///
/// All three formats honour it — `json`, `console` and `pretty`. Writes are
/// serialised, so a record arrives whole even when several threads log at once.
/// Installing a second writer replaces the first; the previous writer is
/// dropped, which flushes it if its `Drop` does.
///
/// Colour is off while a writer is installed: see the module note.
///
/// The writer is taken by value rather than as a `Box`, so a caller passes a
/// `File`, a `Vec<u8>` or its own type directly.
pub fn set_log_output<W: Write + Send + 'static>(writer: W) {
    *crate::_lock::lock(&LOG_OUTPUT) = Some(Box::new(writer));
}

/// Send rendered log records back to stderr, dropping any installed writer.
pub fn clear_log_output() {
    *crate::_lock::lock(&LOG_OUTPUT) = None;
}

/// Whether a host has installed a writer.
///
/// The pretty renderer asks before deciding colour, because a writer is not a
/// destination this crate can establish as a terminal.
pub(crate) fn log_output_installed() -> bool {
    crate::_lock::lock(&LOG_OUTPUT).is_some()
}

/// Flush the installed writer, if there is one.
pub(crate) fn flush_log_output() {
    if let Some(writer) = crate::_lock::lock(&LOG_OUTPUT).as_mut() {
        let _ = writer.flush();
    }
}

/// Write one rendered record, as a line.
///
/// The capture buffer comes first so the test seams keep working with a writer
/// installed, then the writer, then stderr. A write that fails is dropped
/// rather than raised: a logger that panics because the host's pipe closed is
/// worse than a lost record, and there is nowhere to report it to.
pub(crate) fn write_line(capture: Option<&mut Vec<u8>>, line: &str) {
    if let Some(buf) = capture {
        buf.extend_from_slice(line.as_bytes());
        buf.push(b'\n');
        return;
    }
    let mut installed = crate::_lock::lock(&LOG_OUTPUT);
    match installed.as_mut() {
        Some(writer) => {
            let _ = writeln!(writer, "{line}");
        }
        None => eprintln!("{line}"),
    }
}
