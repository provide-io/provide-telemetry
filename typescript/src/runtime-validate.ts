// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Validation for hot-reload runtime overrides.
 *
 * Split out of runtime.ts, which is at the repo's 500-line ceiling. Internal to
 * the runtime module — nothing here is part of the public API.
 */

import type { RuntimeOverrides } from './config.js';
import { ConfigurationError } from './exceptions.js';

function validateNonNegativeNumber(name: string, value: number | undefined): void {
  if (value === undefined) return;
  if (!Number.isFinite(value) || value < 0) {
    // Stryker disable next-line StringLiteral: error message content
    throw new ConfigurationError(`${name} must be >= 0, got ${String(value)}`);
  }
}

/**
 * Check the override fields `setupTelemetry` does not.
 *
 * Rates, backpressure sizes, retry counts and the security/PII limits are all
 * re-checked by `_validateConfig` against the merged config, with the same
 * bounds and the same message wording. Validating them here as well duplicated
 * the rule without changing any outcome: with the rejected update rolled back,
 * disabling either copy left the other one throwing, so neither was observable
 * on its own.
 *
 * The backoff and timeout fields are genuinely only checked here — they are not
 * part of `_validateConfig` — so this is what remains.
 */
/* Stryker disable StringLiteral: field names in validation calls are only used in error messages — mutating them does not change validation behavior */
export function validateRuntimeOverrides(overrides: RuntimeOverrides): void {
  validateNonNegativeNumber('exporterLogsBackoffMs', overrides.exporterLogsBackoffMs);
  validateNonNegativeNumber('exporterTracesBackoffMs', overrides.exporterTracesBackoffMs);
  validateNonNegativeNumber('exporterMetricsBackoffMs', overrides.exporterMetricsBackoffMs);
  validateNonNegativeNumber('exporterLogsTimeoutMs', overrides.exporterLogsTimeoutMs);
  validateNonNegativeNumber('exporterTracesTimeoutMs', overrides.exporterTracesTimeoutMs);
  validateNonNegativeNumber('exporterMetricsTimeoutMs', overrides.exporterMetricsTimeoutMs);
}
/* Stryker restore StringLiteral */
