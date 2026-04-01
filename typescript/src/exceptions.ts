// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Exception hierarchy — mirrors Python provide.telemetry.exceptions.
 */

export class TelemetryError extends Error {
  constructor(message?: string) {
    super(message);
    this.name = 'TelemetryError';
  }
}

/**
 * Raised when telemetry configuration is invalid.
 * Also extends Error directly for maximum compatibility.
 */
export class ConfigurationError extends TelemetryError {
  constructor(message?: string) {
    super(message);
    this.name = 'ConfigurationError';
  }
}
