// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * shutdownTelemetry — flushes and shuts down any OTEL providers registered by
 * registerOtelProviders. Safe to call before process exit or on hot-reload.
 *
 * Uses Promise.allSettled so a failure in one provider's forceFlush/shutdown
 * does not prevent the others from draining.
 */

import { _getRegisteredProviders } from './runtime';

export async function shutdownTelemetry(): Promise<void> {
  const providers = _getRegisteredProviders();
  await Promise.allSettled(providers.map((p) => p.forceFlush?.() ?? Promise.resolve()));
  await Promise.allSettled(providers.map((p) => p.shutdown?.() ?? Promise.resolve()));
}
