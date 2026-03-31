// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * No-op OTEL provider registration for browser environments.
 *
 * In browser builds, the Node.js OTel SDKs are not available. This stub
 * prevents bundlers from pulling in the heavy SDK dependencies while still
 * allowing registerOtelProviders() to be called without error.
 *
 * Note: Cloudflare Workers and Vercel Edge have their own OTel support and
 * should use the default export, not this stub.
 */

import type { TelemetryConfig } from './config';

export async function registerOtelProviders(_cfg: TelemetryConfig): Promise<void> {
  // No-op in browser/edge environments.
}
