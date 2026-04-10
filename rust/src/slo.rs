// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use std::sync::atomic::{AtomicBool, Ordering};

static SLO_INITIALIZED: AtomicBool = AtomicBool::new(false);

pub fn classify_error(status_code: u16) -> String {
    SLO_INITIALIZED.store(true, Ordering::SeqCst);
    match status_code {
        0 => "timeout".to_string(),
        400..=499 => "client_error".to_string(),
        500..=599 => "server_error".to_string(),
        _ => "ok".to_string(),
    }
}

pub fn slo_initialized_for_tests() -> bool {
    SLO_INITIALIZED.load(Ordering::SeqCst)
}

pub fn reset_slo_for_tests() {
    SLO_INITIALIZED.store(false, Ordering::SeqCst);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn slo_test_reset_helper_clears_initialized_flag() {
        let _guard = acquire_test_state_lock();
        reset_slo_for_tests();
        assert!(!slo_initialized_for_tests());

        assert_eq!(classify_error(503), "server_error");
        assert!(slo_initialized_for_tests());

        reset_slo_for_tests();
        assert!(!slo_initialized_for_tests());
    }
}
