// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

#[cfg(feature = "otel-grpc")]
use std::collections::HashMap;

#[cfg(feature = "otel-grpc")]
use http::{HeaderMap, HeaderName, HeaderValue};
#[cfg(feature = "otel-grpc")]
use opentelemetry_otlp::tonic_types::metadata::MetadataMap;

#[cfg(feature = "otel-grpc")]
use crate::errors::TelemetryError;

#[cfg(feature = "otel-grpc")]
pub(super) fn metadata_from_headers(
    headers: &HashMap<String, String>,
) -> Result<MetadataMap, TelemetryError> {
    let mut parsed = HeaderMap::new();
    for (key, value) in headers {
        let name = HeaderName::try_from(key.as_str()).map_err(|err| {
            TelemetryError::new(format!("invalid OTLP header name {key:?}: {err}"))
        })?;
        let value = HeaderValue::try_from(value.as_str()).map_err(|err| {
            TelemetryError::new(format!("invalid OTLP header value for {key:?}: {err}"))
        })?;
        parsed.insert(name, value);
    }
    Ok(MetadataMap::from_headers(parsed))
}

#[cfg(all(test, feature = "otel-grpc"))]
mod tests {
    use super::*;

    #[test]
    fn metadata_from_headers_accepts_valid_headers() {
        let headers = HashMap::from([("authorization".to_string(), "Bearer token".to_string())]);
        let metadata = metadata_from_headers(&headers).expect("valid headers should convert");
        assert!(metadata.get("authorization").is_some());
    }

    #[test]
    fn metadata_from_headers_rejects_invalid_header_name() {
        let headers = HashMap::from([("bad key".to_string(), "value".to_string())]);
        let err = metadata_from_headers(&headers).expect_err("invalid header name must fail");
        assert!(err.message.contains("invalid OTLP header name"));
    }
}
