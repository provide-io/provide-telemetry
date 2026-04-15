// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
//! OTLP transport-protocol resolution.
//!
//! Only compiled under the `otel` cargo feature. Used by the
//! traces/metrics/logs submodules to translate the raw
//! `OTEL_EXPORTER_OTLP_PROTOCOL` strings parsed by `config.rs` into a
//! validated enum and to surface a helpful error when `grpc` is
//! requested without the `otel-grpc` feature.

#![allow(dead_code)] // Wired in subsequent checkpoints (traces/metrics/logs).

use crate::errors::TelemetryError;

/// The OTLP transport protocols recognised by this crate. `Grpc` is
/// only constructible when the `otel-grpc` cargo feature is enabled.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum OtlpProtocol {
    HttpProtobuf,
    HttpJson,
    #[cfg(feature = "otel-grpc")]
    Grpc,
}

/// Default OTLP protocol used when no value is configured. Matches
/// the OpenTelemetry spec's recommended default for SDKs.
const DEFAULT_PROTOCOL: OtlpProtocol = OtlpProtocol::HttpProtobuf;

/// Validate a raw protocol string from config and return the enum.
///
/// Empty string → `DEFAULT_PROTOCOL`. Unknown values → error.
/// `grpc` returns an error when the `otel-grpc` feature is not
/// enabled, with a message pointing the user at the right cargo
/// feature.
pub(super) fn resolve_protocol(raw: &str) -> Result<OtlpProtocol, TelemetryError> {
    match raw.trim() {
        "" => Ok(DEFAULT_PROTOCOL),
        "http/protobuf" => Ok(OtlpProtocol::HttpProtobuf),
        "http/json" => Ok(OtlpProtocol::HttpJson),
        "grpc" => {
            #[cfg(feature = "otel-grpc")]
            {
                Ok(OtlpProtocol::Grpc)
            }
            #[cfg(not(feature = "otel-grpc"))]
            {
                Err(TelemetryError::new(
                    "OTEL_EXPORTER_OTLP_PROTOCOL=grpc requires the `otel-grpc` cargo feature; \
                     rebuild with --features otel-grpc or use http/protobuf",
                ))
            }
        }
        other => Err(TelemetryError::new(format!(
            "unknown OTLP protocol {other:?}; expected one of: http/protobuf, http/json, grpc",
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_string_defaults_to_http_protobuf() {
        assert_eq!(resolve_protocol("").unwrap(), OtlpProtocol::HttpProtobuf);
        assert_eq!(resolve_protocol("   ").unwrap(), OtlpProtocol::HttpProtobuf);
    }

    #[test]
    fn http_protobuf_and_json_accepted() {
        assert_eq!(
            resolve_protocol("http/protobuf").unwrap(),
            OtlpProtocol::HttpProtobuf
        );
        assert_eq!(
            resolve_protocol("http/json").unwrap(),
            OtlpProtocol::HttpJson
        );
    }

    #[test]
    fn unknown_protocol_returns_error_listing_valid_values() {
        let err = resolve_protocol("kafka").expect_err("unknown should fail");
        assert!(
            err.message.contains("unknown OTLP protocol"),
            "unexpected: {}",
            err.message
        );
        assert!(
            err.message.contains("http/protobuf") && err.message.contains("grpc"),
            "error must list valid values: {}",
            err.message
        );
    }

    #[cfg(not(feature = "otel-grpc"))]
    #[test]
    fn grpc_without_feature_returns_helpful_error() {
        let err = resolve_protocol("grpc").expect_err("grpc without feature should fail");
        assert!(
            err.message.contains("otel-grpc"),
            "error must mention the cargo feature: {}",
            err.message
        );
    }

    #[cfg(feature = "otel-grpc")]
    #[test]
    fn grpc_with_feature_is_accepted() {
        assert_eq!(resolve_protocol("grpc").unwrap(), OtlpProtocol::Grpc);
    }
}
