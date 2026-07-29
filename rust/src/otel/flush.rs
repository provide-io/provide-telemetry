// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Drain without teardown — force-flush installed providers, leave them installed.
//!
//! The drain half of the shutdown path. Each provider is cloned out of its slot
//! rather than taken, so telemetry keeps working afterwards, and each flush runs
//! under the bounded-shutdown deadline (see [`super::bounded_flush`]).

use std::sync::Arc;

use super::{logs, metrics, traces};

/// Force-flush the installed provider, leaving it installed and usable.
///
/// The drain half of the shutdown path: the provider is cloned out of its slot
/// rather than taken, so telemetry keeps working afterwards. Returns false when
/// the flush was abandoned at the bounded-shutdown deadline.
pub(crate) fn flush_logger_provider() -> bool {
    let provider = {
        let guard = crate::_lock::lock(logs::logger_provider_slot());
        guard
            .as_ref()
            .map(|installed| Arc::clone(&installed.provider))
    };
    let Some(provider) = provider else {
        return true;
    };

    super::bounded_flush("logs", move || {
        let _ = provider.force_flush();
    })
}

/// Force-flush the installed provider, leaving it installed and usable.
///
/// The drain half of the shutdown path: the provider is cloned out of its slot
/// rather than taken, so telemetry keeps working afterwards. Returns false when
/// the flush was abandoned at the bounded-shutdown deadline.
pub(crate) fn flush_tracer_provider() -> bool {
    let provider = {
        let guard = crate::_lock::lock(traces::tracer_provider_slot());
        guard
            .as_ref()
            .map(|installed| Arc::clone(&installed.provider))
    };
    let Some(provider) = provider else {
        return true;
    };

    super::bounded_flush("traces", move || {
        let _ = provider.force_flush();
    })
}

/// Force-flush the installed provider, leaving it installed and usable.
///
/// The drain half of the shutdown path: the provider is cloned out of its slot
/// rather than taken, so telemetry keeps working afterwards. Returns false when
/// the flush was abandoned at the bounded-shutdown deadline.
pub(crate) fn flush_meter_provider() -> bool {
    let provider = {
        let guard = crate::_lock::lock(metrics::meter_provider_slot());
        guard
            .as_ref()
            .map(|installed| Arc::clone(&installed.provider))
    };
    let Some(provider) = provider else {
        return true;
    };

    super::bounded_flush("metrics", move || {
        let _ = provider.force_flush();
    })
}
