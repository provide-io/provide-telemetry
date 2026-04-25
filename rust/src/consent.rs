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

fn log_level_order(level: Option<&str>) -> usize {
    match level.unwrap_or_default().to_ascii_uppercase().as_str() {
        "TRACE" => 0,
        "DEBUG" => 1,
        "INFO" => 2,
        "WARNING" | "WARN" => 3,
        "ERROR" => 4,
        "CRITICAL" => 5,
        _ => 0,
    }
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
