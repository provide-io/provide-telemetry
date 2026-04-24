// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::collections::HashMap;

use provide_telemetry::testing::acquire_test_state_lock;
use provide_telemetry::{reconfigure_telemetry, shutdown_telemetry};

const ENV_KEYS: &[&str] = &[
    "PROVIDE_TELEMETRY_SERVICE_NAME",
    "PROVIDE_TELEMETRY_ENV",
    "PROVIDE_LOG_INCLUDE_TIMESTAMP",
];

fn with_env(vars: &[(&str, &str)], test: impl FnOnce()) {
    let mut snapshot = HashMap::new();
    for key in ENV_KEYS {
        snapshot.insert((*key).to_string(), std::env::var(key).ok());
        std::env::remove_var(key);
    }
    for (key, value) in vars {
        snapshot.insert((*key).to_string(), std::env::var(key).ok());
        std::env::set_var(key, value);
    }

    test();

    for (key, value) in snapshot {
        match value {
            Some(value) => std::env::set_var(key, value),
            None => std::env::remove_var(key),
        }
    }
}

#[test]
fn runtime_test_reconfigure_telemetry_none_surfaces_env_parse_errors() {
    let _guard = acquire_test_state_lock();
    let _ = shutdown_telemetry();
    provide_telemetry::otel::_reset_otel_for_tests();

    with_env(
        &[
            ("PROVIDE_TELEMETRY_SERVICE_NAME", "from-env"),
            ("PROVIDE_LOG_INCLUDE_TIMESTAMP", "not-a-bool"),
        ],
        || {
            let err = reconfigure_telemetry(None).expect_err("invalid env must fail reconfigure");
            assert!(err.message.contains("PROVIDE_LOG_INCLUDE_TIMESTAMP"));
        },
    );
}
