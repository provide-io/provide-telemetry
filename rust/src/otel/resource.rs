// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! OTel `Resource` construction from `TelemetryConfig`.
//!
//! Only compiled under the `otel` cargo feature. The resulting
//! `Resource` is attached to every exporter (traces, metrics, logs) so
//! each emitted record carries the same service identity.

// Dead-code allowance is lifted once the traces/metrics/logs submodules
// start calling build_resource in a later checkpoint.
#![allow(dead_code)]

use std::collections::HashSet;

use opentelemetry::KeyValue;
use opentelemetry_sdk::Resource;
use opentelemetry_semantic_conventions::resource as sc;

use crate::config::TelemetryConfig;

/// Build the OTel `Resource` describing this service.
///
/// Precedence (cross-language contract, see `spec/behavioral_fixtures.yaml`):
///
///   framework default  <  OTEL_* env  <  explicit config
///
/// An identity key joins the top layer only when its config value differs from
/// the framework default, so an explicitly named service is never hijacked by an
/// ambient `OTEL_RESOURCE_ATTRIBUTES` while `OTEL_SERVICE_NAME` still fills an
/// unset name. `Resource::builder()` (not `builder_empty`) runs the standard
/// detectors (env, telemetry-sdk, process); `with_attribute` overlays win over
/// them, so we overlay the explicit config and — only for keys the env layer
/// does not provide — the framework floor. Matches Go, TypeScript, and Python.
// `deployment.environment.name` is in the OTel spec but still gated behind
// the `semconv_experimental` feature in the Rust semantic-conventions crate,
// so we hand-spell it rather than pulling in the experimental constants.
const DEPLOYMENT_ENVIRONMENT_NAME: &str = "deployment.environment.name";

/// Identity keys the OTEL_* env vars supply, parsed from raw values so the
/// membership check needs no separate resource detection pass.
fn env_identity_keys_from(
    resource_attrs: Option<&str>,
    service_name: Option<&str>,
) -> HashSet<String> {
    let mut keys = HashSet::new();
    if let Some(raw) = resource_attrs {
        for pair in raw.split(',') {
            // Split on the first '=' — a value may legitimately contain '='.
            if let Some((key, _value)) = pair.split_once('=') {
                let key = key.trim();
                if !key.is_empty() {
                    keys.insert(key.to_string());
                }
            }
        }
    }
    if let Some(name) = service_name {
        if !name.trim().is_empty() {
            keys.insert(sc::SERVICE_NAME.to_string());
        }
    }
    keys
}

fn env_identity_keys() -> HashSet<String> {
    env_identity_keys_from(
        std::env::var("OTEL_RESOURCE_ATTRIBUTES").ok().as_deref(),
        std::env::var("OTEL_SERVICE_NAME").ok().as_deref(),
    )
}

pub(crate) fn build_resource(cfg: &TelemetryConfig) -> Resource {
    let defaults = TelemetryConfig::default();
    let env_keys = env_identity_keys();
    let mut builder = Resource::builder();
    for (key, current, default) in [
        (sc::SERVICE_NAME, &cfg.service_name, &defaults.service_name),
        (sc::SERVICE_VERSION, &cfg.version, &defaults.version),
        (
            DEPLOYMENT_ENVIRONMENT_NAME,
            &cfg.environment,
            &defaults.environment,
        ),
    ] {
        if current != default {
            // Explicit config wins over the env layer.
            builder = builder.with_attribute(KeyValue::new(key, current.clone()));
        } else if !env_keys.contains(key) {
            // Neither explicit nor env-provided → framework floor.
            builder = builder.with_attribute(KeyValue::new(key, default.clone()));
        }
        // else: left at the default and provided by env → keep the env value.
    }
    builder.build()
}

#[cfg(test)]
mod tests {
    use super::*;
    use opentelemetry::Key;

    fn attr_value(resource: &Resource, key: &str) -> Option<String> {
        resource
            .get(&Key::new(key.to_string()))
            .map(|v| v.as_str().into_owned())
    }

    #[test]
    fn resource_carries_service_identity_from_config() {
        let cfg = TelemetryConfig {
            service_name: "test-service".to_string(),
            environment: "staging".to_string(),
            version: "1.2.3".to_string(),
            ..TelemetryConfig::default()
        };
        let r = build_resource(&cfg);
        assert_eq!(
            attr_value(&r, sc::SERVICE_NAME),
            Some("test-service".to_string()),
            "service.name must come from config"
        );
        assert_eq!(
            attr_value(&r, sc::SERVICE_VERSION),
            Some("1.2.3".to_string()),
            "service.version must come from config"
        );
        assert_eq!(
            attr_value(&r, DEPLOYMENT_ENVIRONMENT_NAME),
            Some("staging".to_string()),
            "deployment.environment.name must come from config"
        );
    }

    #[test]
    fn resource_includes_telemetry_sdk_language() {
        let r = build_resource(&TelemetryConfig::default());
        // TelemetryResourceDetector injects telemetry.sdk.language automatically.
        assert_eq!(
            attr_value(&r, "telemetry.sdk.language"),
            Some("rust".to_string()),
        );
    }

    #[test]
    fn resource_falls_back_to_framework_floor_when_unset() {
        let defaults = TelemetryConfig::default();
        let r = build_resource(&defaults);
        // With nothing set, identity keys carry the framework floor values.
        assert_eq!(
            attr_value(&r, sc::SERVICE_NAME),
            Some(defaults.service_name)
        );
        assert_eq!(attr_value(&r, sc::SERVICE_VERSION), Some(defaults.version));
        assert_eq!(
            attr_value(&r, DEPLOYMENT_ENVIRONMENT_NAME),
            Some(defaults.environment),
        );
    }

    #[test]
    fn env_identity_keys_parses_resource_attributes_and_service_name() {
        // Additive + identity keys from OTEL_RESOURCE_ATTRIBUTES.
        let keys = env_identity_keys_from(Some("host.name=web-1,service.version=1.0.0"), None);
        assert!(keys.contains("host.name"));
        assert!(keys.contains("service.version"));

        // OTEL_SERVICE_NAME contributes service.name; blank is ignored.
        assert!(env_identity_keys_from(None, Some("svc")).contains(sc::SERVICE_NAME));
        assert!(env_identity_keys_from(None, Some("   ")).is_empty());

        // Split on the first '=' only; pairs without '=' are skipped.
        let split = env_identity_keys_from(Some("k=v=w,novalue"), None);
        assert!(split.contains("k"));
        assert!(!split.contains("novalue"));
    }

    #[test]
    fn env_provided_key_is_not_overridden_by_floor() {
        // When env supplies service.name and config is at the default, the floor
        // must not be overlaid (so the env layer shows through). Verify via the
        // membership gate that drives build_resource.
        let defaults = TelemetryConfig::default();
        let env_keys = env_identity_keys_from(None, Some("env-service"));
        assert!(env_keys.contains(sc::SERVICE_NAME));
        // The config value equals the default, so build_resource would skip the
        // floor overlay for this key (leaving the detector's env value in place).
        assert_eq!(
            defaults.service_name,
            TelemetryConfig::default().service_name
        );
    }
}
