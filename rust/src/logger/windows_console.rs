// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Whether the destination renders ANSI, and on Windows making it so.
//!
//! A console renders escape sequences only once
//! `ENABLE_VIRTUAL_TERMINAL_PROCESSING` is set on its handle. Windows Terminal
//! and current conhost set it themselves; legacy conhost does not and prints
//! `ESC[36m` literally. `is_terminal()` cannot tell those apart — every console
//! is a terminal — so the pretty renderer was emitting escapes on the one
//! platform least able to render them.
//!
//! Cross-language parity with `go/logger_console_windows.go` and
//! `csharp/src/Provide.Telemetry/ConsolePrep.cs`; the contract is
//! `windows_console.virtual_terminal` in `spec/telemetry-api.yaml`.
//!
//! The console's *output code page* is deliberately untouched. It decides how a
//! console decodes the bytes written to it, but Rust never writes bytes to one:
//! `std`'s windows stdio probes the handle and, for a console, converts to
//! UTF-16 and calls `WriteConsoleW`. Only C# encodes through a code page, and
//! only C# sets it.

/// Whether ANSI escapes written to stderr will be rendered as escapes.
#[cfg(not(windows))]
pub(crate) fn ansi_supported() -> bool {
    use std::io::IsTerminal;
    std::io::stderr().is_terminal()
}

/// Restore whatever [`ansi_supported`] changed. Nothing, away from Windows.
#[cfg(not(windows))]
pub(crate) fn restore() {}

#[cfg(windows)]
mod imp {
    use std::io::IsTerminal;
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::OnceLock;

    const ENABLE_VIRTUAL_TERMINAL_PROCESSING: u32 = 0x0004;
    const STD_ERROR_HANDLE: u32 = 0xFFFF_FFF4; // -12 as an unsigned DWORD

    // Declared here rather than pulled in as a dependency. Three calls whose
    // arguments are plain integers do not justify one, and the sibling SDKs
    // reach the same API the same way: Go through syscall.NewLazyDLL, C#
    // through DllImport.
    #[link(name = "kernel32")]
    extern "system" {
        fn GetStdHandle(n_std_handle: u32) -> isize;
        fn GetConsoleMode(h_console_handle: isize, lp_mode: *mut u32) -> i32;
        fn SetConsoleMode(h_console_handle: isize, dw_mode: u32) -> i32;
    }

    /// The mode this process found, so shutdown can put it back. `u32::MAX` is
    /// the sentinel for "nothing was changed", which a real console mode cannot
    /// be: the documented bits do not fill the word.
    static PREVIOUS_MODE: AtomicU32 = AtomicU32::new(u32::MAX);
    static SUPPORTED: OnceLock<bool> = OnceLock::new();

    /// Enable VT once per process, reporting whether escapes will render.
    ///
    /// Memoised because the renderer asks per record, and a console mode call
    /// per log line would be both wasteful and a race with anything else in the
    /// process adjusting the same handle.
    pub(crate) fn ansi_supported() -> bool {
        *SUPPORTED.get_or_init(|| {
            if !std::io::stderr().is_terminal() {
                return false;
            }
            // SAFETY: three kernel32 calls with integer arguments and one
            // out-parameter that lives on this stack frame for the duration.
            // GetConsoleMode fails rather than writing through the pointer when
            // the handle is not a console.
            unsafe {
                let handle = GetStdHandle(STD_ERROR_HANDLE);
                let mut mode: u32 = 0;
                if GetConsoleMode(handle, &mut mode) == 0 {
                    return false;
                }
                if mode & ENABLE_VIRTUAL_TERMINAL_PROCESSING != 0 {
                    return true;
                }
                if SetConsoleMode(handle, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING) == 0 {
                    return false;
                }
                PREVIOUS_MODE.store(mode, Ordering::Relaxed);
                true
            }
        })
    }

    /// Put the console mode back the way the host had it.
    pub(crate) fn restore() {
        let previous = PREVIOUS_MODE.swap(u32::MAX, Ordering::Relaxed);
        if previous == u32::MAX {
            return;
        }
        // SAFETY: as above; `previous` is a mode this process read from the
        // same handle.
        unsafe {
            SetConsoleMode(GetStdHandle(STD_ERROR_HANDLE), previous);
        }
    }
}

#[cfg(windows)]
pub(crate) fn ansi_supported() -> bool {
    imp::ansi_supported()
}

#[cfg(windows)]
pub(crate) fn restore() {
    imp::restore();
}
