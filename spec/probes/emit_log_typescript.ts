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
import { setupTelemetry, getLogger, setTraceContext } from '../../typescript/src/index.js';

const TRACE_ID = '0af7651916cd43dd8448eb211c80319c';
const SPAN_ID = 'b7ad6b7169203331';

setupTelemetry();
setTraceContext(TRACE_ID, SPAN_ID);

// Use the public API — getLogger() returns the canonical Logger interface.
const log = getLogger('probe');
log.info({ event: 'log.output.parity' }, 'log.output.parity');
