// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * @provide-io/telemetry/prometheus — the Tier 2 Prometheus pull surface. Node only.
 *
 * metricsHandler() returns a `(req, res)` listener for node:http, Express or
 * Connect; renderPrometheus() returns one collection's body and content type
 * for any other server. Both serve what registerOtelProviders() attached when
 * OTEL_METRICS_EXPORTER includes prometheus, and answer 503 with a one-line
 * reason before that, after shutdown, or when the host owns the MeterProvider.
 * See prometheus_metrics in spec/telemetry-api.yaml.
 *
 * The standalone (Tier 3) listener needs no import: it is started by
 * registerOtelProviders() from PROVIDE_METRICS_PROMETHEUS_LISTEN.
 */

import type { IncomingMessage, ServerResponse } from 'node:http';
import { writeResponse } from './prom-http.js';
import { responseFor } from './prom-pull.js';

export { renderPrometheus } from './prom-pull.js';
export type { PrometheusResponseBody } from './prom-pull.js';

/** A node:http request listener; Express and Connect accept it as middleware too. */
export type MetricsHandler = (req: IncomingMessage, res: ServerResponse) => void;

/**
 * The Tier 2 pull handler; mount it at whatever path the host likes.
 *
 * Serves GET and HEAD, answers 405 otherwise, and 503 with a one-line reason
 * until the Prometheus reader is attached and after shutdown. Each request
 * runs one collection: observable callbacks, then the health snapshot.
 */
export function metricsHandler(): MetricsHandler {
  return (req, res) => {
    // A server request always carries its method.
    void responseFor(req.method as string, req.headers.accept).then((answer) => {
      writeResponse(res, answer);
    });
  };
}
