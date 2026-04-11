// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::{Mutex, OnceLock};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ConsentLevel {
    Full,
    Functional,
    Minimal,
    None,
}

static CONSENT_LEVEL: OnceLock<Mutex<ConsentLevel>> = OnceLock::new();

fn consent_level() -> &'static Mutex<ConsentLevel> {
    CONSENT_LEVEL.get_or_init(|| Mutex::new(ConsentLevel::Full))
}

pub fn set_consent_level(level: ConsentLevel) {
    *consent_level().lock().expect("consent lock poisoned") = level;
}

pub fn get_consent_level() -> ConsentLevel {
    *consent_level().lock().expect("consent lock poisoned")
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
mod tests {
    use super::*;

    // Tests log_level_order for every arm individually so cargo-mutants cannot
    // delete any arm without causing a failure.
    #[test]
    fn log_level_order_covers_all_arms() {
        assert_eq!(log_level_order(Some("TRACE")), 0);
        assert_eq!(log_level_order(Some("DEBUG")), 1);
        assert_eq!(log_level_order(Some("INFO")), 2);
        assert_eq!(log_level_order(Some("WARNING")), 3);
        assert_eq!(log_level_order(Some("WARN")), 3); // alias — same arm
        assert_eq!(log_level_order(Some("ERROR")), 4);
        assert_eq!(log_level_order(Some("CRITICAL")), 5);
        assert_eq!(log_level_order(None), 0); // unwrap_or_default → ""
        assert_eq!(log_level_order(Some("unknown")), 0);
    }

    // INFO must be strictly between DEBUG and WARNING.
    #[test]
    fn log_level_order_info_between_debug_and_warning() {
        assert!(log_level_order(Some("INFO")) > log_level_order(Some("DEBUG")));
        assert!(log_level_order(Some("INFO")) < log_level_order(Some("WARNING")));
    }

    // CRITICAL must be strictly above ERROR.
    #[test]
    fn log_level_order_critical_above_error() {
        assert!(log_level_order(Some("CRITICAL")) > log_level_order(Some("ERROR")));
    }
}
