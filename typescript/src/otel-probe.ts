// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Live-provider probes for the global OpenTelemetry signals.
 *
 * The facade needs to know whether a real SDK owns a global. For traces that
 * decides sampling authority — the SDK's sampler is then in charge and the
 * facade must not stack its own rate on top (facadeRate x sdkRate). For both
 * traces and metrics it decides what getRuntimeStatus() reports.
 *
 * A "we called setGlobal*Provider() ourselves" flag answers the wrong question:
 * a host application running its own NodeSDK owns the OTel globals without ever
 * calling registerOtelProviders(), so trace.getTracer() / metrics.getMeter()
 * resolve that foreign provider and export normally while the flag stays false.
 *
 * Probing the global API answers for foreign providers too, and it reads
 * through the same `trace` / `metrics` objects the emit paths use — probe and
 * provider can never disagree about which one is in play.
 */

import { metrics, trace, type TracerProvider } from '@opentelemetry/api';

/** The API's ProxyTracerProvider hands out the real provider via getDelegate(). */
type MaybeProxyProvider = TracerProvider & { getDelegate?: () => TracerProvider };

/** SDK providers implement the flush/shutdown lifecycle pair; no-op ones do not. */
type MaybeLifecycleProvider = { forceFlush?: unknown; shutdown?: unknown };

/**
 * True when `provider` is a live SDK provider rather than an API no-op.
 *
 * Duck-typed on the forceFlush()/shutdown() pair that every SDK provider
 * implements — BasicTracerProvider, NodeTracerProvider, WebTracerProvider,
 * MeterProvider, and whatever a host NodeSDK installs — and that the API's
 * no-op providers (and an undelegated ProxyTracerProvider) do not.
 *
 * Deliberately not `instanceof`: the registered provider often comes from a
 * *different copy* of @opentelemetry/api than ours — the globals are shared
 * through a globalThis symbol, the classes are not — and instanceof is false
 * across copies. A provider implementing neither method reads as no-op, which
 * leaves the facade in charge: the conservative direction, and the behaviour
 * that predates these probes.
 */
function _hasProviderLifecycle(provider: object): boolean {
  const candidate = provider as MaybeLifecycleProvider;
  return typeof candidate.forceFlush === 'function' && typeof candidate.shutdown === 'function';
}

/** True when `provider` — or, for a proxy, its delegate — is a live tracer provider. */
export function _isLiveTracerProvider(provider: TracerProvider): boolean {
  const proxy = provider as MaybeProxyProvider;
  return _hasProviderLifecycle(
    typeof proxy.getDelegate === 'function' ? proxy.getDelegate() : provider,
  );
}

/** True when a live OTel tracer provider owns the global — SDK sampling is authoritative. */
export function _isLiveTracerProviderInstalled(): boolean {
  return _isLiveTracerProvider(trace.getTracerProvider());
}

/**
 * True when a live OTel meter provider owns the global.
 *
 * No delegate to unwrap here: the metrics API has no proxy provider, so
 * getMeterProvider() hands back either the registered provider or its no-op.
 */
export function _isLiveMeterProviderInstalled(): boolean {
  return _hasProviderLifecycle(metrics.getMeterProvider());
}
