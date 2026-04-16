// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.
//
// Emit one canonical JSON log line to stderr for cross-language parity checking.
//
// Env vars (set by run_behavioral_parity.py --check-output before invoking):
//   PROVIDE_LOG_FORMAT=json
//   PROVIDE_TELEMETRY_SERVICE_NAME=probe
//   PROVIDE_LOG_INCLUDE_TIMESTAMP=false
//   PROVIDE_LOG_LEVEL=INFO

import process from 'node:process';
import { setupTelemetry, getLogger } from '../../typescript/src/index.js';

const serviceName = process.env['PROVIDE_TELEMETRY_SERVICE_NAME'] ?? 'probe';
const includeTimestamp = !['false', '0', 'no'].includes(
  (process.env['PROVIDE_LOG_INCLUDE_TIMESTAMP'] ?? '').toLowerCase(),
);

setupTelemetry({
  serviceName,
  environment: process.env['PROVIDE_TELEMETRY_ENVIRONMENT'] ?? '',
  version: process.env['PROVIDE_TELEMETRY_VERSION'] ?? '',
  logFormat: 'json',
  logLevel: 'info',
  logIncludeTimestamp: includeTimestamp,
  consoleOutput: true,
});

// Use the public API — getLogger() returns the canonical Logger interface.
const log = getLogger('probe');
log.info({ event: 'log.output.parity' }, 'log.output.parity');
