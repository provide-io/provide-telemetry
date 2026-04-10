// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

use sha2::{Digest, Sha256};

fn normalize_frames(stack: &str) -> Vec<String> {
    stack
        .lines()
        .filter_map(|line| {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                return None;
            }
            let normalized = trimmed
                .replace('\\', "/")
                .split('/')
                .last()
                .unwrap_or(trimmed)
                .to_ascii_lowercase();
            Some(normalized)
        })
        .take(3)
        .collect()
}

pub fn compute_error_fingerprint(error_name: &str, stack: Option<&str>) -> String {
    let mut parts = vec![error_name.to_ascii_lowercase()];
    if let Some(stack) = stack {
        parts.extend(normalize_frames(stack));
    }

    let mut hasher = Sha256::new();
    hasher.update(parts.join(":").as_bytes());
    format!("{:x}", hasher.finalize())[..12].to_string()
}
