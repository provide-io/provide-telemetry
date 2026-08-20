// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

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

pub fn reset_consent_for_tests() {
    set_consent_level(ConsentLevel::Full);
}

#[cfg(test)]
#[path = "consent_tests.rs"]
mod tests;
