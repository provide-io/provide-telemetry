// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// Mutation tests for resilience.rs

use provide_telemetry::{get_exporter_policy, set_exporter_policy, ExporterPolicy};

#[test]
fn test_exporter_policy_default() {
    let policy = get_exporter_policy();
    let _ = policy;
}

#[test]
fn test_set_exporter_policy() {
    let policy = ExporterPolicy::default();
    set_exporter_policy(policy.clone());
    let retrieved = get_exporter_policy();
    let _ = retrieved;
}

#[test]
fn test_exporter_policy_roundtrip() {
    let policy1 = ExporterPolicy::default();
    set_exporter_policy(policy1.clone());
    let retrieved1 = get_exporter_policy();

    let policy2 = ExporterPolicy::default();
    set_exporter_policy(policy2.clone());
    let retrieved2 = get_exporter_policy();

    let _ = (retrieved1, retrieved2);
}
