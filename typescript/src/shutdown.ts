// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * shutdownTelemetry — flushes and shuts down any OTEL providers registered by
 * registerOtelProviders. Safe to call before process exit or on hot-reload.
 *
 * Uses Promise.allSettled so a failure in one provider's forceFlush/shutdown
 * does not prevent the others from draining.
 */

import { _clearProviderState, _getRegisteredProviders } from './runtime';
import { _resetRootLogger } from './logger';

export async function shutdownTelemetry(): Promise<void> {
  const providers = _getRegisteredProviders();
  await Promise.allSettled(providers.map((p) => p.forceFlush?.() ?? Promise.resolve()));
  await Promise.allSettled(providers.map((p) => p.shutdown?.() ?? Promise.resolve()));
  _clearProviderState();
  _resetRootLogger();
}
