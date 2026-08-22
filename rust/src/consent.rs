// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum ConsentLevel {
    #[default]
    Full,
    Functional,
    Minimal,
    None,
}

static CONSENT_LEVEL: OnceLock<Mutex<ConsentLevel>> = OnceLock::new();

#[cfg_attr(test, mutants::skip)] // Equivalent mutants only rewrite ConsentLevel::Full as Default::default().
fn default_consent_level_mutex() -> Mutex<ConsentLevel> {
    Mutex::new(ConsentLevel::Full)
}

fn consent_level() -> &'static Mutex<ConsentLevel> {
    CONSENT_LEVEL.get_or_init(default_consent_level_mutex)
}

pub fn set_consent_level(level: ConsentLevel) {
    *crate::_lock::lock(consent_level()) = level;
}

pub fn get_consent_level() -> ConsentLevel {
    *crate::_lock::lock(consent_level())
}

/// The operator's consent opt-out. Read by `setup_telemetry` and by the lazy
/// logger path rather than by `TelemetryConfig`, so it binds whether or not a
/// config was passed in.
pub(crate) const CONSENT_LEVEL_ENV_VAR: &str = "PROVIDE_CONSENT_LEVEL";

/// Parse one spelling of a consent level, trimmed and ASCII-upper-cased so
/// `" none "` and `minimal` both count. `None` for anything unrecognised.
fn parse_consent_level(raw: &str) -> Option<ConsentLevel> {
    match raw.trim().to_ascii_uppercase().as_str() {
        "FULL" => Some(ConsentLevel::Full),
        "FUNCTIONAL" => Some(ConsentLevel::Functional),
        "MINIMAL" => Some(ConsentLevel::Minimal),
        "NONE" => Some(ConsentLevel::None),
        _ => None,
    }
}

/// One reading of `PROVIDE_CONSENT_LEVEL`, classified before anything acts
/// on it, so the decision is a pure function of the text.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ConsentEnv {
    /// Empty or whitespace-only: the operator has no opinion, as if unset.
    Blank,
    /// One of the four recognised spellings.
    Level(ConsentLevel),
    /// Set, non-empty and not a consent level: an opt-out that was misspelled.
    Invalid,
}

fn classify_consent_env(raw: &str) -> ConsentEnv {
    if raw.trim().is_empty() {
        return ConsentEnv::Blank;
    }
    match parse_consent_level(raw) {
        Some(level) => ConsentEnv::Level(level),
        None => ConsentEnv::Invalid,
    }
}

/// Set once the invalid-value warning has been written, so a process hears
/// about its misspelled opt-out exactly once however many times the variable
/// is read. Cleared by [`reset_consent_for_tests`].
static INVALID_CONSENT_ENV_WARNED: AtomicBool = AtomicBool::new(false);

/// `true` on the first call per process (and after a reset), `false` after.
fn should_warn_invalid_consent_once() -> bool {
    !INVALID_CONSENT_ENV_WARNED.swap(true, Ordering::SeqCst)
}

/// The warning for an unrecognised value, naming it exactly as given --
/// untrimmed, so the operator sees the stray whitespace too.
fn invalid_consent_env_message(raw: &str) -> String {
    format!(
        "[provide-telemetry] {CONSENT_LEVEL_ENV_VAR}=\"{raw}\" is not one of FULL, FUNCTIONAL, \
         MINIMAL, NONE; consent set to NONE (fail-closed)"
    )
}

/// Apply one reading of the variable (`None` when unset) and return the
/// warning to write, if any. Kept apart from the `eprintln!` so tests can
/// assert the exact text and the once-per-process rule directly.
fn apply_consent_env(raw: Option<&str>) -> Option<String> {
    let raw = raw?;
    match classify_consent_env(raw) {
        ConsentEnv::Blank => None,
        ConsentEnv::Level(level) => {
            set_consent_level(level);
            None
        }
        ConsentEnv::Invalid => {
            set_consent_level(ConsentLevel::None);
            should_warn_invalid_consent_once().then(|| invalid_consent_env_message(raw))
        }
    }
}

/// Read `PROVIDE_CONSENT_LEVEL` and apply it.
///
/// An unset or blank (empty or whitespace-only) variable leaves the current
/// level untouched rather than resetting it to FULL: it means the operator has
/// no opinion, and a level narrowed programmatically with
/// [`set_consent_level`] survives it. A recognised value -- trimmed,
/// case-insensitive; `FULL`, `FUNCTIONAL`, `MINIMAL` or `NONE` -- is applied.
/// Any other value fails closed: consent becomes [`ConsentLevel::None`] on
/// every call, and one warning per process naming the value is written to
/// stderr -- deliberately outside this crate's own logger, which the `None`
/// just applied would silence. The variable is an opt-out control, and the one
/// failure an opt-out must not have is a typo that silently leaves collection
/// on.
pub fn load_consent_from_env() {
    let raw = std::env::var(CONSENT_LEVEL_ENV_VAR).ok();
    if let Some(message) = apply_consent_env(raw.as_deref()) {
        eprintln!("{message}");
    }
}

/// Rank a level for the consent gates, resolving through the one shared table.
///
/// An unrecognised level ranks INFO here rather than the old local default of
/// 0/TRACE. Both sit below the WARN and ERROR gates below, so no consent
/// decision changes. FATAL does change: it used to be unrecognised and was
/// dropped as if it were the least severe record in the ladder.
fn log_level_order(level: Option<&str>) -> u8 {
    crate::logger::levels::level_order(level.unwrap_or_default())
}

pub fn should_allow(signal: &str, log_level: Option<&str>) -> bool {
    match get_consent_level() {
        ConsentLevel::Full => true,
        ConsentLevel::None => false,
        ConsentLevel::Functional => match signal {
            "logs" => log_level_order(log_level) >= 3,
            "context" => false,
            _ => true,
        },
        ConsentLevel::Minimal => match signal {
            "logs" => log_level_order(log_level) >= 4,
            _ => false,
        },
    }
}

/// Restore the default level and re-arm the once-per-process warning for an
/// unrecognised `PROVIDE_CONSENT_LEVEL`.
pub fn reset_consent_for_tests() {
    set_consent_level(ConsentLevel::Full);
    INVALID_CONSENT_ENV_WARNED.store(false, Ordering::SeqCst);
}

#[cfg(test)]
#[path = "consent_tests.rs"]
mod tests;
