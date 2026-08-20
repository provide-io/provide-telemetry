// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
use super::*;

#[test]
fn level_order_ranks_critical_above_error_and_defaults_unknown_to_info() {
    assert_eq!(level_order("ERROR"), 4);
    // CRITICAL and FATAL used to fold onto ERROR at 4. They are the top of the
    // ladder, and a CRITICAL threshold must exclude ERROR rather than admit it.
    assert_eq!(level_order("critical"), 5);
    assert_eq!(level_order("fatal"), 5);
    assert_eq!(level_order("not-a-level"), 2);
}
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
