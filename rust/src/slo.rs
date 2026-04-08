// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

pub fn classify_error(status_code: u16) -> String {
    match status_code {
        0 => "timeout".to_string(),
        400..=499 => "client_error".to_string(),
        500..=599 => "server_error".to_string(),
        _ => "ok".to_string(),
    }
}
