// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/** Writing a scrape answer to a node:http response; shared by metricsHandler() and the listener. */

import type { ServerResponse } from 'node:http';
import type { PrometheusResponse } from './prom-pull.js';

/** Send an answer: its status, its headers in order, then Content-Length and the body. */
export function writeResponse(res: ServerResponse, answer: PrometheusResponse): void {
  res.statusCode = answer.status;
  for (const [name, value] of answer.headers) res.setHeader(name, value);
  res.setHeader('content-length', Buffer.byteLength(answer.body));
  res.end(answer.body);
}
