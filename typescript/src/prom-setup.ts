// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * Wiring between registerOtelProviders() / shutdownTelemetry() and the
 * Prometheus pull path.
 *
 * The listener module imports node:http, node:https and node:tls, so it is
 * loaded here through dynImportOtel's runtime-only import rather than a static
 * one: bundlers cannot follow it, and the browser build never contains the
 * listener. It is only loaded under Node, and only once a config asks for it.
 */

import { _isNodeLike } from './config.js';
import { prometheusListenerEnabled, type PrometheusSettings } from './config-prometheus.js';
import { getHealthSnapshot, setSetupError } from './health.js';
import { dynImportOtel } from './otel-dynimport.js';

/** Every listener failure recorded as setupError starts with this. */
export const LISTENER_ERROR_PREFIX = 'prometheus listener: ';

/** The listener module's surface, as prom-listener.ts exports it. */
export interface ListenerModule {
  syncListener(
    settings: PrometheusSettings,
    enabled: boolean,
    report: (error: string) => void,
  ): Promise<void>;
  stopListener(): Promise<void>;
  listenerAddress(): { host: string; port: number } | undefined;
}

// Relative to otel-dynimport.js, which sits beside prom-listener.js in dist/.
const LISTENER_MODULE = './prom-listener.js';

let loaded: ListenerModule | undefined;
let loader: () => Promise<ListenerModule> = () => dynImportOtel(LISTENER_MODULE);

/** Replace the listener loader (tests), or restore the real one. */
export function _setListenerLoaderForTests(next?: () => Promise<ListenerModule>): void {
  loader = next ?? (() => dynImportOtel(LISTENER_MODULE));
  loaded = undefined;
}

function report(message: string): void {
  setSetupError(message);
  console.warn(`[provide/telemetry] metrics.prometheus_listener.failed: ${message}`);
}

/**
 * Start, restart or stop the listener to match cfg.
 *
 * Failures, a listener that cannot be loaded included, are recorded as the
 * health snapshot's setupError and logged, never thrown. A listener error left
 * from an earlier sync is cleared first, so the snapshot always describes the
 * latest attempt; other setup errors are left alone.
 */
export async function syncPrometheusListener(cfg: PrometheusSettings): Promise<void> {
  if (getHealthSnapshot().setupError?.startsWith(LISTENER_ERROR_PREFIX)) setSetupError(null);
  const enabled = prometheusListenerEnabled(cfg);
  if (loaded === undefined) {
    if (!enabled) return; // nothing can be running
    if (!_isNodeLike()) {
      report(`${LISTENER_ERROR_PREFIX}requires Node.js`);
      return;
    }
    try {
      loaded = await loader();
    } catch (err) {
      report(`${LISTENER_ERROR_PREFIX}${String(err)}`);
      return;
    }
  }
  await loaded.syncListener(cfg, enabled, (message) => {
    setSetupError(message);
  });
}

/** Stop the listener if one was ever loaded. */
export async function stopPrometheusListener(): Promise<void> {
  if (loaded !== undefined) await loaded.stopListener();
}

/** The running listener's bound address, or undefined. */
export function prometheusListenerAddress(): { host: string; port: number } | undefined {
  return loaded?.listenerAddress();
}
