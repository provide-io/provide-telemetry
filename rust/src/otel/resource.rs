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

use opentelemetry::KeyValue;
use opentelemetry_sdk::Resource;
use opentelemetry_semantic_conventions::resource as sc;

use crate::config::TelemetryConfig;

/// Build the OTel `Resource` describing this service.
///
/// The resource carries the attributes that identify *what* produced
/// each telemetry record. We populate the attributes that all four
/// language implementations agree on: service name, service version,
/// deployment environment, and telemetry SDK language.
///
/// The `Resource::builder()` (not `builder_empty`) is used so that
/// OpenTelemetry's standard resource detectors (env, telemetry-sdk,
/// process) also contribute attributes. `OTEL_RESOURCE_ATTRIBUTES` is
/// honoured via the bundled `EnvResourceDetector` — no custom parsing
/// needed.
// `deployment.environment.name` is in the OTel spec but still gated behind
// the `semconv_experimental` feature in the Rust semantic-conventions crate,
// so we hand-spell it rather than pulling in the experimental constants.
const DEPLOYMENT_ENVIRONMENT_NAME: &str = "deployment.environment.name";

pub(crate) fn build_resource(cfg: &TelemetryConfig) -> Resource {
    Resource::builder()
        .with_attribute(KeyValue::new(sc::SERVICE_NAME, cfg.service_name.clone()))
        .with_attribute(KeyValue::new(sc::SERVICE_VERSION, cfg.version.clone()))
        .with_attribute(KeyValue::new(
            DEPLOYMENT_ENVIRONMENT_NAME,
            cfg.environment.clone(),
        ))
        .build()
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
}
