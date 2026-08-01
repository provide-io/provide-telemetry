// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//

/// Why a [`TelemetryError`] was raised. The crate's public functions all return
/// `TelemetryError`, so the kind is what lets a caller act on a specific failure —
/// the Rust analogue of Python's `except ProviderImmutableError` and Go's
/// `errors.As(err, &*ProviderImmutableError)`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum TelemetryErrorKind {
    #[default]
    General,
    /// A provider-changing reconfiguration rejected because providers are live.
    /// The process must restart to apply it.
    ProviderImmutable,
}

#[derive(thiserror::Error, Debug, Clone, PartialEq, Eq)]
#[error("{message}")]
pub struct TelemetryError {
    pub message: String,
    pub kind: TelemetryErrorKind,
}

impl TelemetryError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            kind: TelemetryErrorKind::General,
        }
    }

    /// True when this error reports a rejected provider-changing reconfiguration.
    pub fn is_provider_immutable(&self) -> bool {
        self.kind == TelemetryErrorKind::ProviderImmutable
    }
}

impl From<ProviderImmutableError> for TelemetryError {
    fn from(err: ProviderImmutableError) -> Self {
        Self {
            message: err.message,
            kind: TelemetryErrorKind::ProviderImmutable,
        }
    }
}

#[derive(thiserror::Error, Debug, Clone, PartialEq, Eq)]
#[error("{message}")]
pub struct ConfigurationError {
    pub message: String,
}

impl ConfigurationError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

#[derive(thiserror::Error, Debug, Clone, PartialEq, Eq)]
#[error("{message}")]
pub struct EventSchemaError {
    pub message: String,
}

impl EventSchemaError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

#[derive(thiserror::Error, Debug, Clone, PartialEq, Eq)]
#[error("{message}")]
pub struct ProviderImmutableError {
    pub message: String,
}

impl ProviderImmutableError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

#[allow(non_camel_case_types)]
pub type provider_immutable_error = ProviderImmutableError;
