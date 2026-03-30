// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Basic logging — mirrors Python examples/telemetry/basic_logging.py
 *
 * Run:
 *   npx tsx examples/basic_logging.ts
 */

import { getLogger, setupTelemetry } from '../src/index.js';

setupTelemetry({
  serviceName: 'my-app',
  logLevel: 'debug',
  consoleOutput: true,
  captureToWindow: false,
});

const log = getLogger('api');

log.info({ event: 'server_started', port: 3000 });
log.debug({ event: 'request_received', method: 'GET', path: '/api/users' });
log.info({ event: 'request_ok', status: 200, duration_ms: 42 });
log.warn({ event: 'rate_limit_approaching', requests_per_minute: 450 });
log.error({ event: 'upstream_timeout', upstream: 'db', timeout_ms: 5000, error: 'ETIMEDOUT' });

// Named child logger for a specific component
const dbLog = getLogger('db');
dbLog.debug({ event: 'query_start', table: 'users', query: 'SELECT *' });
dbLog.info({ event: 'query_ok', table: 'users', rows: 25, duration_ms: 8 });

// Child logger with bound fields
const requestLog = log.child({ request_id: 'req-abc123', user_id: 7 });
requestLog.info({ event: 'auth_ok', role: 'admin' });
requestLog.info({ event: 'action_complete', action: 'update_profile' });
