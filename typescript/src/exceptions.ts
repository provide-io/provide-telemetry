// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Exception hierarchy — mirrors Python undef.telemetry.exceptions.
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
