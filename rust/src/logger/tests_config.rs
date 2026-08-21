// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

use super::*;

#[test]
fn effective_level_does_not_match_partial_string() {
    let cfg = cfg_with_module_level("foo", "DEBUG");
    assert_eq!(
        effective_level_threshold("foobar", &cfg),
        2,
        "foobar must not match prefix foo (no dot separator)"
    );
}

#[test]
fn effective_level_matches_dot_separated_child() {
    let cfg = cfg_with_module_level("foo", "DEBUG");
    assert_eq!(
        effective_level_threshold("foo.bar", &cfg),
        1,
        "foo.bar must match prefix foo via dot separator"
    );
}

#[test]
fn effective_level_matches_exact_module_name() {
    let cfg = cfg_with_module_level("foo", "DEBUG");
    assert_eq!(
        effective_level_threshold("foo", &cfg),
        1,
        "exact name must match"
    );
}

#[test]
fn effective_level_empty_prefix_matches_everything() {
    let cfg = cfg_with_module_level("", "DEBUG");
    assert_eq!(
        effective_level_threshold("anything.at.all", &cfg),
        1,
        "empty prefix must match any target"
    );
}

#[test]
fn effective_level_longest_prefix_wins() {
    let mut module_levels = HashMap::new();
    module_levels.insert("foo".to_string(), "WARN".to_string());
    module_levels.insert("foo.bar".to_string(), "DEBUG".to_string());
    let cfg = crate::config::LoggingConfig {
        level: "INFO".to_string(),
        module_levels,
        ..crate::config::LoggingConfig::default()
    };
    assert_eq!(
        effective_level_threshold("foo.bar.baz", &cfg),
        1,
        "longer prefix must win over shorter"
    );
}

#[test]
fn active_logging_config_prefers_override_then_runtime_then_env() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    std::env::set_var("PROVIDE_LOG_FORMAT", "json");
    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "false");
    assert_eq!(active_logging_config().fmt, "json");
    assert!(!active_logging_config().include_timestamp);

    set_active_config(Some(TelemetryConfig {
        logging: crate::config::LoggingConfig {
            level: "WARN".to_string(),
            fmt: "console".to_string(),
            include_timestamp: false,
            ..crate::config::LoggingConfig::default()
        },
        ..TelemetryConfig::default()
    }));
    assert_eq!(active_logging_config().level, "WARN");
    assert_eq!(active_logging_config().fmt, "console");

    configure_logging(trace_json_config());
    assert_eq!(active_logging_config(), trace_json_config());
}

#[test]
fn active_logging_config_falls_back_to_defaults_when_env_parse_fails() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool");

    assert_eq!(
        active_logging_config(),
        crate::config::LoggingConfig::default()
    );

    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
}

#[test]
fn reset_logging_config_for_tests_clears_programmatic_override() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    std::env::set_var("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool");

    let override_cfg = trace_json_config();
    configure_logging(override_cfg.clone());
    assert_eq!(active_logging_config(), override_cfg);

    reset_logging_config_for_tests();
    assert_eq!(
        active_logging_config(),
        crate::config::LoggingConfig::default()
    );

    std::env::remove_var("PROVIDE_LOG_INCLUDE_TIMESTAMP");
}

#[test]
fn get_logger_before_setup_applies_env_log_sampling_policy() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    std::env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "0");
    let log = get_logger(Some("tests.lazy.env.sampling"));
    log.info("sampled.out");

    assert!(Logger::drain_events_for_tests().is_empty());
    assert_eq!(crate::health::get_health_snapshot().dropped_logs, 1);
    std::env::remove_var("PROVIDE_SAMPLING_LOGS_RATE");
}

#[test]
fn get_logger_before_setup_ignores_invalid_env_log_sampling_policy() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    std::env::set_var("PROVIDE_SAMPLING_LOGS_RATE", "not-a-float");
    let log = get_logger(Some("tests.lazy.env.invalid_sampling"));
    log.info("invalid.sampling.env");

    let events = Logger::drain_events_for_tests();
    assert_eq!(events.len(), 1);
    assert_eq!(events[0].message, "invalid.sampling.env");
    std::env::remove_var("PROVIDE_SAMPLING_LOGS_RATE");
}

/// PROVIDE_CONSENT_LEVEL is read on the lazy path too -- and independently of
/// PROVIDE_SAMPLING_LOGS_RATE, which is deliberately left unset here so the
/// sampling short-circuit cannot be what skipped it.
#[test]
fn get_logger_before_setup_applies_env_consent_level() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    std::env::set_var(crate::consent::CONSENT_LEVEL_ENV_VAR, "NONE");
    let log = get_logger(Some("tests.lazy.env.consent"));
    assert_eq!(crate::get_consent_level(), ConsentLevel::None);
    log.info("consent.none.lazy");

    assert!(Logger::drain_events_for_tests().is_empty());
    std::env::remove_var(crate::consent::CONSENT_LEVEL_ENV_VAR);
    reset_consent_for_tests();
}

/// With the variable unset, the lazy path leaves a level set in code alone.
#[test]
fn get_logger_before_setup_leaves_programmatic_consent_when_env_unset() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    set_consent_level(ConsentLevel::Minimal);
    let _ = get_logger(Some("tests.lazy.env.consent_unset"));

    assert_eq!(crate::get_consent_level(), ConsentLevel::Minimal);
    reset_consent_for_tests();
}

/// Once setup has run, get_logger() no longer consults the environment, so a
/// level narrowed programmatically after setup is never clobbered by it.
#[test]
fn get_logger_after_setup_does_not_reload_consent_from_env() {
    let _guard = acquire_test_state_lock();
    reset_logger_state();

    crate::setup::setup_telemetry(None).expect("setup should succeed");
    set_consent_level(ConsentLevel::Minimal);
    std::env::set_var(crate::consent::CONSENT_LEVEL_ENV_VAR, "NONE");
    let _ = get_logger(Some("tests.lazy.env.consent_after_setup"));

    assert_eq!(crate::get_consent_level(), ConsentLevel::Minimal);
    std::env::remove_var(crate::consent::CONSENT_LEVEL_ENV_VAR);
    let _ = crate::setup::shutdown_telemetry(None);
    reset_consent_for_tests();
}
