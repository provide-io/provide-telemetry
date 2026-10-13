// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Reporting reserved root fields whose caller value a stamped value replaced
 * (reserved_root_fields.replacement_reporting in spec/telemetry-api.yaml).
 *
 * Replacing a field silently loses the caller's data — a `version` meaning a
 * schema version, say — so each replacement adds to
 * `reservedFieldReplacements`, and the first replacement of each field in the
 * process logs one warning naming the field, never its value. The write hook
 * stamps only after admission, so a refused record is neither counted nor
 * warned about, and the warning is logged from inside the hook, so it reaches
 * the output before the record it explains.
 */

import { _incrementHealth } from './health.js';

/** Canonical order: the order replacements are warned about in. */
export const RESERVED_FIELDS = ['service', 'env', 'version', 'trace_id', 'span_id'] as const;
export const RESERVED_WARNING_EVENT = 'logger.reserved_field.replaced';
export const RESERVED_WARNING_LOGGER = 'provide.telemetry.logger';

const _warned = new Set<string>();

// Set while a warning is being logged. The warning is an ordinary record and
// runs the same stamping, so a reserved field in bound context would otherwise
// count again, against a record the caller never wrote.
let _warning = false;

/**
 * Stamp `value` under `key` on `record` when the SDK has one, noting in
 * `replaced` when it replaces a different caller value.
 */
export function stampReserved(
  record: Record<string, unknown>,
  key: string,
  value: string | undefined | null,
  replaced: string[],
): void {
  if (!value) return;
  if (key in record && record[key] !== value) replaced.push(key);
  record[key] = value;
}

/** Count `replaced`, and warn through `warn` about each field replaced for the first time. */
export function reportReservedReplacements(
  replaced: readonly string[],
  warn: (field: string) => void,
): void {
  if (replaced.length === 0 || _warning) return;
  _incrementHealth('reservedFieldReplacements', replaced.length);
  const first = RESERVED_FIELDS.filter((field) => replaced.includes(field) && !_warned.has(field));
  for (const field of first) _warned.add(field);
  _warning = true;
  try {
    for (const field of first) warn(field);
  } finally {
    _warning = false;
  }
}

/** Forget which fields have been warned about (test helper). */
export function _resetReservedWarningsForTests(): void {
  _warned.clear();
  _warning = false;
}
