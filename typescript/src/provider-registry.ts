// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Bookkeeping for the OTel providers this library installed.
 *
 * Split out of runtime.ts, which is at the repo's 500-line ceiling. Everything
 * here is re-exported from runtime.ts, so consumers keep importing from there.
 */

/** The three telemetry signals, as used to key per-signal results. */
export type SignalName = 'logs' | 'traces' | 'metrics';

/** Minimal interface for providers that can be flushed and shut down cleanly. */
export interface ShutdownableProvider {
  forceFlush?(): Promise<void>;
  shutdown?(): Promise<void>;
}

// Stryker disable next-line BooleanLiteral: initial false is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _providersRegistered = false;
// Stryker disable next-line ArrayDeclaration: initial [] is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _registeredProviders: ShutdownableProvider[] = [];
// Parallel to _registeredProviders: _providerSignals[i] names the signal
// _registeredProviders[i] drains. Empty when the caller did not tag them.
// Stryker disable next-line ArrayDeclaration: initial [] is overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _providerSignals: SignalName[] = [];
// Logs is the one signal whose provider state is bookkept at install time:
// traces and metrics are probed against the OTel globals instead (see
// getRuntimeStatus), so a host application's own SDK counts as installed. The
// logs API lives in the optional @opentelemetry/api-logs peer, which cannot be
// imported synchronously here, so there is nothing to probe against.
// Stryker disable next-line BooleanLiteral: initial value overwritten by _resetRuntimeForTests() in every test beforeEach — equivalent mutant
let _logsProviderInstalled = false;

/**
 * Store the live providers so shutdownTelemetry can flush and drain them.
 *
 * `signals[i]` names the signal `providers[i]` drains, so flushSignals can
 * report each one separately instead of collapsing three endpoints into one
 * boolean. Omitting it leaves the providers untagged and the per-signal flush
 * degrades to the aggregate — the shutdown path drains everything either way.
 */
export function _storeRegisteredProviders(
  providers: ShutdownableProvider[],
  signals?: SignalName[],
): void {
  _registeredProviders = providers;
  _providerSignals = signals ?? [];
}

/** Return the currently registered providers (snapshot). */
export function _getRegisteredProviders(): ShutdownableProvider[] {
  return [..._registeredProviders];
}

/**
 * Return the registered providers that carry a signal tag, keyed by signal.
 *
 * A signal absent from the map has no provider of ours behind it: nothing
 * installed, or — for traces and metrics, whose status is probed against the
 * OTel globals — a provider the host application registered, which is not ours
 * to drain.
 */
export function _getProvidersBySignal(): Partial<Record<SignalName, ShutdownableProvider>> {
  const bySignal: Partial<Record<SignalName, ShutdownableProvider>> = {};
  for (const [index, signal] of _providerSignals.entries()) {
    const provider = _registeredProviders[index];
    if (provider) bySignal[signal] = provider;
  }
  return bySignal;
}

/**
 * The signal a registered provider drains, or undefined when it has no tag.
 *
 * Identity lookup over the same positional arrays `_getProvidersBySignal` walks,
 * so it answers only for providers `_storeRegisteredProviders` was handed.
 * A provider that is not ours, or one registered without a signal tag, has no
 * answer here — and undefined is the honest one, since nothing recorded which
 * exporter it belongs to.
 */
export function _signalForProvider(provider: ShutdownableProvider): SignalName | undefined {
  // No `index < 0` guard: indexOf returns -1 for a provider we never stored,
  // and _providerSignals[-1] is already undefined, so the guard could not
  // change the answer. Keeping it would only add a branch no test can
  // distinguish — mutation testing flagged it as exactly that.
  return _providerSignals[_registeredProviders.indexOf(provider)];
}

/** Called by registerOtelProviders once providers are live. */
export function _markProvidersRegistered(): void {
  _providersRegistered = true;
}

/** Return true if OTEL providers have been registered. */
export function _areProvidersRegistered(): boolean {
  return _providersRegistered;
}

/** Called by registerOtelProviders once the OTLP log provider is live. */
export function _setLogsProviderInstalled(installed: boolean): void {
  _logsProviderInstalled = installed;
}

/** Whether the OTLP log provider we install is live. */
export function _isLogsProviderInstalled(): boolean {
  return _logsProviderInstalled;
}

/** Drop every provider record. Called from both shutdown and the test reset. */
export function _clearProviderRegistry(): void {
  _providersRegistered = false;
  _registeredProviders = [];
  // Equivalent mutant: the two arrays are positional and cleared together, and
  // _getProvidersBySignal only emits a tag whose provider is present. With
  // _registeredProviders empty, no value here is observable — and the next
  // _storeRegisteredProviders overwrites both.
  // Stryker disable next-line ArrayDeclaration
  _providerSignals = [];
  _logsProviderInstalled = false;
}
