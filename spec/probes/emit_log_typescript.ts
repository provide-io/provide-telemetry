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
import { setupTelemetry } from '../../typescript/src/index.js';
import { makeWriteHook } from '../../typescript/src/logger.js';
import pino from 'pino';

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
  consoleOutput: false,
});

const hook = makeWriteHook();

// Custom stream: run the pino-serialised object through the write hook
// (which enriches it in-place), then emit the canonical JSON to stderr.
const stream = {
  write(msg: string): void {
    try {
      const obj = JSON.parse(msg.trimEnd()) as Record<string, unknown>;
      hook(obj as object);
      // Normalise pino's numeric level to canonical uppercase string.
      const levelNum = obj['level'] as number | undefined;
      if (typeof levelNum === 'number') {
        const levelNames: Record<number, string> = {
          10: 'TRACE', 20: 'DEBUG', 30: 'INFO', 40: 'WARN', 50: 'ERROR', 60: 'FATAL',
        };
        obj['level'] = levelNames[levelNum] ?? String(levelNum);
      }
      // Strip pino noise fields before emitting.
      for (const k of ['pid', 'hostname', 'v', 'time']) delete obj[k];
      process.stderr.write(JSON.stringify(obj) + '\n');
    } catch {
      // Ignore malformed lines (pino flush sentinels etc.).
    }
  },
};

const root = pino(
  {
    base: { service: serviceName },
    level: 'info',
  },
  stream as unknown as pino.DestinationStream,
);

root.info({ event: 'log.output.parity' }, 'log.output.parity');
