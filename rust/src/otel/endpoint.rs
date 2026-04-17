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

/// Validate an OTLP endpoint URL.
///
/// Returns `Ok(())` for valid HTTP(S) URLs with a host and a valid or
/// absent port. Returns `Err` for:
/// - unparsable URLs
/// - non-`http`/`https` schemes (e.g. `ftp://`)
/// - missing host
/// - non-numeric or out-of-range ports (caught by `url::Url` parser)
///
/// The OTel OTLP HTTP exporter builder accepts the endpoint string as a
/// raw `http::Uri` without performing scheme/host/port validation, so
/// callers must call this function before passing the endpoint to the
/// builder.
pub(super) fn validate_endpoint(endpoint: &str) -> Result<(), TelemetryError> {
    let parsed = Url::parse(endpoint)
        .map_err(|e| TelemetryError::new(format!("invalid OTLP endpoint {endpoint:?}: {e}")))?;
    match parsed.scheme() {
        "http" | "https" => {}
        scheme => {
            return Err(TelemetryError::new(format!(
                "invalid OTLP endpoint scheme {scheme:?} in {endpoint:?}: expected http or https",
            )));
        }
    }
    if parsed.host().is_none() {
        return Err(TelemetryError::new(format!(
            "invalid OTLP endpoint (no host): {endpoint:?}",
        )));
    }
    // Port 0 is reserved and not a valid OTLP endpoint port.
    if parsed.port() == Some(0) {
        return Err(TelemetryError::new(format!(
            "invalid OTLP endpoint (port 0 is reserved): {endpoint:?}",
        )));
    }
    // url::Url rejects non-numeric and out-of-range ports during parsing.
    // However, it silently accepts empty ports ("http://host:" → port=None).
    // Detect by checking for a trailing colon in the authority after any
    // IPv6 bracket (avoids false positives from [::1] colons).
    if parsed.port().is_none() {
        let authority = &endpoint[parsed.scheme().len() + 3..]; // skip "scheme://"
        let after_bracket = authority.rsplit(']').next().unwrap_or(authority);
        let host_port = after_bracket.split('/').next().unwrap_or("");
        if host_port.contains(':') {
            return Err(TelemetryError::new(format!(
                "invalid OTLP endpoint (empty port): {endpoint:?}",
            )));
        }
    }
    Ok(())
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

    // --- validate_endpoint tests ---

    #[test]
    fn valid_http_endpoint_is_accepted() {
        assert!(validate_endpoint("http://localhost:4318").is_ok());
        assert!(validate_endpoint("http://collector.example.com/v1/traces").is_ok());
        assert!(validate_endpoint("https://otel.example.com:4317/v1/metrics").is_ok());
    }

    #[test]
    fn valid_https_endpoint_without_port_is_accepted() {
        assert!(validate_endpoint("https://collector.example.com").is_ok());
    }

    #[test]
    fn invalid_scheme_returns_error() {
        let err = validate_endpoint("ftp://host:4318").expect_err("ftp should fail");
        assert!(
            err.message.contains("scheme") && err.message.contains("ftp"),
            "error must mention bad scheme: {}",
            err.message
        );
    }

    #[test]
    fn grpc_scheme_rejected() {
        let err = validate_endpoint("grpc://host:4317").expect_err("grpc scheme should fail");
        assert!(
            err.message.contains("scheme"),
            "error must mention bad scheme: {}",
            err.message
        );
    }

    #[test]
    fn completely_unparseable_url_returns_error() {
        let err = validate_endpoint("not_a_url").expect_err("invalid URL should fail");
        assert!(
            err.message.contains("invalid OTLP endpoint"),
            "error must describe the problem: {}",
            err.message
        );
    }

    #[test]
    fn out_of_range_port_returns_error() {
        // url::Url rejects ports > 65535 at parse time.
        let err = validate_endpoint("http://host:99999").expect_err("out-of-range port should fail");
        assert!(
            err.message.contains("invalid OTLP endpoint"),
            "error must describe the problem: {}",
            err.message
        );
    }

    #[test]
    fn empty_host_returns_error() {
        // "http://:4318/path" has an empty authority; url crate rejects this.
        let err = validate_endpoint("http://:4318/path").expect_err("empty host should fail");
        assert!(
            err.message.contains("invalid OTLP endpoint"),
            "error must describe the problem: {}",
            err.message
        );
    }

    #[test]
    fn empty_port_returns_error() {
        let err = validate_endpoint("http://host:").expect_err("empty port should fail");
        assert!(
            err.message.contains("empty port"),
            "error must mention empty port: {}",
            err.message
        );
    }

    #[test]
    fn empty_port_with_path_returns_error() {
        let err =
            validate_endpoint("http://host:/v1/traces").expect_err("empty port with path should fail");
        assert!(
            err.message.contains("empty port"),
            "error must mention empty port: {}",
            err.message
        );
    }

    #[test]
    fn ipv6_with_valid_port_accepted() {
        assert!(validate_endpoint("http://[::1]:4318").is_ok());
    }

    #[test]
    fn ipv6_no_port_accepted() {
        assert!(validate_endpoint("http://[::1]").is_ok());
    }

    // Parity fixtures from spec/behavioral_fixtures.yaml endpoint_validation section.
    // Keep in sync with the YAML — the Python CI gate validates all languages
    // produce the same accept/reject decisions.

    #[test]
    fn parity_valid_endpoints() {
        let valid = [
            "http://localhost:4318",
            "https://collector.example.com",
            "http://host:4318/v1/traces",
            "http://host",
            "http://[::1]:4318",
            "http://[::1]",
            "https://otel.example.com:4317/v1/metrics",
        ];
        for ep in valid {
            assert!(
                validate_endpoint(ep).is_ok(),
                "expected valid endpoint {ep:?} to be accepted"
            );
        }
    }

    #[test]
    fn parity_invalid_endpoints() {
        let invalid = [
            "",
            "not-a-url",
            "ftp://host:4318",
            "http://",
            "http://host:bad",
            "http://host:-1",
            "http://host:0",
            "http://host:99999",
            "http://host:",
            "http://host:/v1/traces",
        ];
        for ep in invalid {
            assert!(
                validate_endpoint(ep).is_err(),
                "expected invalid endpoint {ep:?} to be rejected"
            );
        }
    }
}
