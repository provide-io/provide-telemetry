// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

//! Adopting a provider a host application installed on the OTel globals.
//!
//! The Python and TypeScript facades detect this for themselves: they resolve
//! their tracer off the global and can ask whether what they got is real. Go
//! duck-types the global provider's `ForceFlush`/`Shutdown` pair to the same
//! end. Rust cannot — `opentelemetry::global::tracer_provider()` returns an
//! opaque `GlobalTracerProvider` whose inner provider is private, with no
//! downcast and no `is_noop`, so there is no way to tell a live SDK provider
//! from the crate's own no-op.
//!
//! So the host asserts it instead. After calling
//! [`adopt_global_providers`], `trace()` routes through `global::tracer(..)` —
//! which already resolves the host's provider — rather than falling back to the
//! no-op span path, and the host's sampler becomes the sampling authority.
//!
//! Adoption never implies ownership: [`shutdown_telemetry`](crate::shutdown_telemetry)
//! releases the assertion without touching the host's providers, and
//! [`flush_telemetry`](crate::flush_telemetry) does not drain them.

use std::sync::atomic::{AtomicBool, Ordering};

static TRACES_ADOPTED: AtomicBool = AtomicBool::new(false);
static METRICS_ADOPTED: AtomicBool = AtomicBool::new(false);

/// Which globals the host is asserting are backed by a live provider.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct AdoptedProviders {
    /// A live `TracerProvider` is installed on the OTel global.
    pub traces: bool,
    /// A live `MeterProvider` is installed on the OTel global.
    pub metrics: bool,
}

impl AdoptedProviders {
    /// Assert both signals — the common case for a host running a full SDK.
    #[must_use]
    pub fn all() -> Self {
        Self {
            traces: true,
            metrics: true,
        }
    }
}

/// Tell the facade that the host has installed live providers on the OTel
/// globals, so emission routes through them instead of the no-op path.
///
/// Call it after the host's own SDK setup and after `setup_telemetry()`, which
/// does not clear the assertion. Passing a field as `false` releases that
/// signal's assertion.
pub fn adopt_global_providers(adopted: AdoptedProviders) {
    TRACES_ADOPTED.store(adopted.traces, Ordering::Release);
    METRICS_ADOPTED.store(adopted.metrics, Ordering::Release);
}

/// Return which globals are currently adopted.
#[must_use]
pub fn adopted_global_providers() -> AdoptedProviders {
    AdoptedProviders {
        traces: TRACES_ADOPTED.load(Ordering::Acquire),
        metrics: METRICS_ADOPTED.load(Ordering::Acquire),
    }
}

/// Drop every assertion without touching the host's providers. Called by
/// `shutdown_telemetry`; the host owns its own SDK's lifecycle.
pub(crate) fn release_adopted_providers() {
    adopt_global_providers(AdoptedProviders::default());
}

/// True when facade spans should go through the global tracer provider.
#[cfg(feature = "otel")]
pub(crate) fn traces_adopted() -> bool {
    TRACES_ADOPTED.load(Ordering::Acquire)
}

/// True when facade measurements should go through the global meter provider.
#[cfg(feature = "otel")]
pub(crate) fn metrics_adopted() -> bool {
    METRICS_ADOPTED.load(Ordering::Acquire)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testing::acquire_test_state_lock;

    #[test]
    fn nothing_is_adopted_by_default() {
        let _guard = acquire_test_state_lock();
        release_adopted_providers();
        assert_eq!(adopted_global_providers(), AdoptedProviders::default());
        assert!(!adopted_global_providers().traces);
        assert!(!adopted_global_providers().metrics);
    }

    #[test]
    fn adoption_is_per_signal() {
        let _guard = acquire_test_state_lock();
        adopt_global_providers(AdoptedProviders {
            traces: true,
            metrics: false,
        });
        assert!(adopted_global_providers().traces);
        assert!(!adopted_global_providers().metrics);
        release_adopted_providers();
    }

    #[test]
    fn all_asserts_both_signals() {
        let _guard = acquire_test_state_lock();
        adopt_global_providers(AdoptedProviders::all());
        assert!(adopted_global_providers().traces);
        assert!(adopted_global_providers().metrics);
        release_adopted_providers();
    }

    // Effective-provider routing only exists when the OTel SDK is compiled in;
    // without it there is nothing to adopt and the flag is inert by design.
    #[cfg(feature = "otel")]
    #[test]
    fn adoption_makes_the_traces_provider_effective() {
        let _guard = acquire_test_state_lock();
        // Establish the premise. Both predicates are gated on the signal not
        // having been switched off by a *loaded* config, and other tests
        // (metrics_tests.rs) install a config with metrics disabled and leave
        // it there, so this must start from no config rather than inherit one.
        crate::testing::reset_telemetry_state();
        release_adopted_providers();
        assert!(!crate::otel::traces_provider_effective());

        adopt_global_providers(AdoptedProviders::all());
        assert!(crate::otel::traces_provider_effective());
        assert!(crate::otel::metrics_provider_effective());

        release_adopted_providers();
    }

    #[test]
    fn shutdown_releases_the_assertion_without_owning_the_providers() {
        let _guard = acquire_test_state_lock();
        adopt_global_providers(AdoptedProviders::all());

        crate::shutdown_telemetry().expect("shutdown should succeed");

        // The host's providers are untouched; only our assertion is dropped.
        assert_eq!(adopted_global_providers(), AdoptedProviders::default());
    }

    // Effective-provider routing only exists when the OTel SDK is compiled in;
    // without it there is nothing to adopt and the flag is inert by design.
    #[cfg(feature = "otel")]
    #[test]
    fn adopted_traces_bypass_facade_sampling() {
        use crate::sampling::{set_sampling_policy, SamplingPolicy, Signal};

        let _guard = acquire_test_state_lock();
        crate::shutdown_telemetry().expect("pre-test shutdown should succeed");
        crate::health::_reset_health_for_tests();
        set_sampling_policy(
            Signal::Traces,
            SamplingPolicy {
                default_rate: 0.0,
                overrides: Default::default(),
            },
        )
        .expect("policy should apply");

        // Without adoption the facade sampler drops the span.
        crate::trace("adopt.unsampled", || {});
        assert_eq!(crate::health::get_health_snapshot().emitted_traces, 0);

        // With it, the host SDK's sampler is the authority and we do not stack.
        adopt_global_providers(AdoptedProviders::all());
        crate::trace("adopt.sampled", || {});
        assert_eq!(crate::health::get_health_snapshot().emitted_traces, 1);

        release_adopted_providers();
        crate::sampling::_reset_sampling_for_tests();
    }
}
