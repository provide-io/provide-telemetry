// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Deprecated re-export shim. Import from './pii' for new code.
 * Retained for semver-stable consumer imports; scheduled for removal in the
 * 1.0.0 major bump.
 */

import { sanitize as _sanitize, DEFAULT_SANITIZE_FIELDS as _DEFAULT_SANITIZE_FIELDS } from './pii';

/**
 * Redact default-and-extra PII fields from a plain object in place.
 *
 * @deprecated Import `sanitize` from `./pii` (or `@provide-io/telemetry`)
 *   instead. This re-export will be removed in the 1.0.0 major release.
 */
export const sanitize = _sanitize;

/**
 * The default set of field names whose values are replaced with "[REDACTED]".
 *
 * @deprecated Import `DEFAULT_SANITIZE_FIELDS` from `./pii` (or
 *   `@provide-io/telemetry`) instead. This re-export will be removed in the
 *   1.0.0 major release.
 */
export const DEFAULT_SANITIZE_FIELDS = _DEFAULT_SANITIZE_FIELDS;
