// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use provide_telemetry::testing::acquire_test_state_lock;
use provide_telemetry::{get_circuit_state, get_exporter_policy, run_with_resilience, Signal};
use provide_telemetry::{resilience, TelemetryError};

async fn ok_unit_operation() -> Result<(), TelemetryError> {
    Ok(())
}

#[test]
fn resilience_missing_state_test_public_surface_reports_internal_corruption() {
    let _guard = acquire_test_state_lock();
    resilience::_reset_resilience_for_tests();

    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    assert_eq!(
        runtime
            .block_on(run_with_resilience(Signal::Logs, ok_unit_operation))
            .expect("healthy state should allow resilience wrapper"),
        Some(())
    );

    resilience::_clear_resilience_state_for_tests();

    let policy_err = get_exporter_policy(Signal::Logs).expect_err("missing policy must error");
    assert!(policy_err.message.contains("unknown signal"));

    let run_err = runtime
        .block_on(run_with_resilience(Signal::Logs, ok_unit_operation))
        .expect_err("missing policy must bubble through run_with_resilience");
    assert!(run_err.message.contains("unknown signal"));

    let circuit_err = get_circuit_state(Signal::Logs).expect_err("missing circuit must error");
    assert!(circuit_err.message.contains("unknown signal"));

    resilience::_reset_resilience_for_tests();
}
