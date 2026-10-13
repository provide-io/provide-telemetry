// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! Stage names of the canonical signal pipeline, `spec/pipeline_fixtures.yaml`,
//! and the test-only hook that reports them.
//!
//! hardening, pii, receipt and local have no constant: each leaves a mark on
//! the record or the sinks that a test can read directly, so only the gates and
//! the bookkeeping around them, plus the backend bridge, report here. An
//! admission refusal leaves no mark anywhere else, so without the hook a test
//! can see that a record was refused but not which stages ran around it.

use std::sync::RwLock;

pub(crate) const STAGE_CONSENT: &str = "consent";
pub(crate) const STAGE_SAMPLING: &str = "sampling";
pub(crate) const STAGE_BACKPRESSURE: &str = "backpressure";
#[cfg(feature = "otel")]
pub(crate) const STAGE_BACKEND: &str = "backend";
pub(crate) const STAGE_HEALTH: &str = "health";
pub(crate) const STAGE_RELEASE: &str = "release";

/// A reader lock rather than a mutex: every record on every thread reads it,
/// and readers never contend with each other.
static STAGE_HOOK: RwLock<Option<fn(&'static str)>> = RwLock::new(None);

/// Install, or with `None` remove, the hook told each stage the logs pipeline
/// passes. Test-only seam, as in the C# and Go SDKs.
pub fn set_pipeline_stage_hook(hook: Option<fn(&'static str)>) {
    *crate::_lock::rwlock_write(&STAGE_HOOK) = hook;
}

pub(crate) fn pipeline_stage(stage: &'static str) {
    let hook = *crate::_lock::rwlock_read(&STAGE_HOOK);
    if let Some(hook) = hook {
        hook(stage);
    }
}

/// End a path admission control refused. The gate that refused has already
/// counted the drop, and no ticket was taken, so the release is the ticket
/// accounting the fixture requires on every path rather than a queue operation.
pub(crate) fn close_refused() {
    pipeline_stage(STAGE_HEALTH);
    pipeline_stage(STAGE_RELEASE);
}
