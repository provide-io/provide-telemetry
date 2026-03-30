// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Runtime reconfiguration helpers.
 * Mirrors Python undef.telemetry.runtime.
 */

import { ConfigurationError } from './exceptions';
import { type TelemetryConfig, configFromEnv, setupTelemetry } from './config';

/** Minimal interface for providers that can be flushed and shut down cleanly. */
export interface ShutdownableProvider {
  forceFlush?(): Promise<void>;
  shutdown?(): Promise<void>;
}

let _activeConfig: TelemetryConfig | null = null;
// Stryker disable next-line BooleanLiteral: initial false is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _providersRegistered = false;
// Stryker disable next-line ArrayDeclaration: initial [] is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _registeredProviders: ShutdownableProvider[] = [];

/** Store the live providers so shutdownTelemetry can flush and drain them. */
export function _storeRegisteredProviders(providers: ShutdownableProvider[]): void {
  _registeredProviders = providers;
}

/** Return the currently registered providers (snapshot). */
export function _getRegisteredProviders(): ShutdownableProvider[] {
  return [..._registeredProviders];
}

/** Called by registerOtelProviders once providers are live. */
export function _markProvidersRegistered(): void {
  _providersRegistered = true;
}

/** Return true if OTEL providers have been registered. */
export function _areProvidersRegistered(): boolean {
  return _providersRegistered;
}

/** Return the active runtime config (or env-derived defaults if none set). */
export function getRuntimeConfig(): TelemetryConfig {
  return _activeConfig ?? configFromEnv();
}

/** Merge overrides into the active config and call setupTelemetry. */
export function updateRuntimeConfig(overrides: Partial<TelemetryConfig>): void {
  const base = getRuntimeConfig();
  _activeConfig = { ...base, ...overrides };
  setupTelemetry(_activeConfig);
}

/** Reload config from env vars and apply it. */
export function reloadRuntimeFromEnv(): void {
  _activeConfig = configFromEnv();
  setupTelemetry(_activeConfig);
}

const PROVIDER_CHANGING_FIELDS: (keyof TelemetryConfig)[] = [
  'otelEnabled',
  'otlpEndpoint',
  'otlpHeaders',
];

/**
 * Apply config changes.
 * Throws ConfigurationError if provider-changing fields differ and providers are already registered.
 * Otherwise delegates to setupTelemetry.
 */
export function reconfigureTelemetry(config: Partial<TelemetryConfig>): void {
  const current = getRuntimeConfig();
  const proposed: TelemetryConfig = { ...current, ...config };

  if (_providersRegistered) {
    const changed = PROVIDER_CHANGING_FIELDS.some(
      (k) => JSON.stringify(current[k]) !== JSON.stringify(proposed[k]),
    );
    if (changed) {
      throw new ConfigurationError(
        'Cannot change OTEL provider config after providers are initialized; restart the process',
      );
    }
  }

  setupTelemetry(proposed);
  _activeConfig = proposed;
}

export function _resetRuntimeForTests(): void {
  _activeConfig = null;
  _providersRegistered = false;
  _registeredProviders = [];
}
