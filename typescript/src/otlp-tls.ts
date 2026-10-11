// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * The OTLP push TLS files must be readable before an exporter is built.
 *
 * See prometheus_metrics.push_security in spec/telemetry-api.yaml. The OTel
 * exporters read OTEL_EXPORTER_OTLP_[SIGNAL_]CERTIFICATE, CLIENT_CERTIFICATE and
 * CLIENT_KEY themselves, but a file they cannot read only earns a diag warning
 * and a silent fall back to the system trust store. Each builder asks
 * tlsReady() first: a file that cannot be read or loaded leaves that signal's
 * exporter unbuilt, and registerOtelProviders() reports it as setupError.
 * Mirrors Python provide.telemetry._otlp_tls.
 *
 * Node built-ins are imported at runtime, and only when a variable is set, so
 * the browser bundle (which reaches otel.ts) never pulls them in.
 */

import { nodeEnv } from './config-env.js';
import { dynImportOtel } from './otel-dynimport.js';

export const SEPARATOR = '; ';

/** Reads one environment variable; undefined when unset (or outside Node). */
type Env = (name: string) => string | undefined;

/** [path, variable name]: the per-signal variable when set, else the shared one. */
function resolveVar(signal: string, kind: string, env: Env): [string, string] {
  let name = `OTEL_EXPORTER_OTLP_${signal.toUpperCase()}_${kind}`;
  if (!env(name)) name = `OTEL_EXPORTER_OTLP_${kind}`;
  return [env(name) ?? '', name];
}

const PEM_CERTIFICATE = /-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/g;

/**
 * The first configured TLS file for signal that cannot be read or loaded,
 * described as `VAR=path: reason`, or undefined.
 *
 * The CA file must hold at least one certificate, and a client certificate and
 * key, when both are set, must form a pair.
 */
export async function unreadableTls(
  signal: string,
  env: Env = nodeEnv,
): Promise<string | undefined> {
  const [ca, caName] = resolveVar(signal, 'CERTIFICATE', env);
  const [cert, certName] = resolveVar(signal, 'CLIENT_CERTIFICATE', env);
  const [key, keyName] = resolveVar(signal, 'CLIENT_KEY', env);
  if (!ca && !cert && !key) return undefined;
  const fs = (await dynImportOtel('node:fs')) as typeof import('node:fs');
  const contents = new Map<string, Buffer>();
  for (const [name, path] of [
    [caName, ca],
    [certName, cert],
    [keyName, key],
  ] as const) {
    if (!path) continue;
    try {
      contents.set(path, fs.readFileSync(path));
    } catch (err) {
      return `${name}=${path}: ${String((err as NodeJS.ErrnoException).code)}`;
    }
  }
  if (ca) {
    const { X509Certificate } = (await dynImportOtel(
      'node:crypto',
    )) as typeof import('node:crypto');
    // createSecureContext() accepts a CA with no usable certificate, so each
    // PEM block is parsed. No block at all: iterating null throws, caught below.
    const blocks = (contents.get(ca) as Buffer).toString('utf8').match(PEM_CERTIFICATE);
    try {
      for (const block of blocks as RegExpMatchArray) new X509Certificate(block);
    } catch {
      return `${caName}=${ca}: no PEM certificates`;
    }
  }
  // Only a cert and key together can mismatch; either alone loads without complaint.
  {
    const { createSecureContext } = (await dynImportOtel('node:tls')) as typeof import('node:tls');
    try {
      createSecureContext({ cert: contents.get(cert), key: contents.get(key) });
    } catch (err) {
      return `${certName}=${cert}, ${keyName}=${key}: ${(err as Error).message}`;
    }
  }
  return undefined;
}

const problems: string[] = [];
let lastReported: string | null = null;

/** Whether signal's exporter may be built; records and logs the reason when it may not. */
export async function tlsReady(signal: string): Promise<boolean> {
  const problem = await unreadableTls(signal);
  if (problem === undefined) return true;
  problems.push(problem);
  console.warn(`[provide/telemetry] otlp.tls_file_unreadable: signal=${signal} error=${problem}`);
  return false;
}

/**
 * Start a setup attempt: forget earlier problems, and clear a setupError this
 * module set last time, leaving other setup errors alone.
 */
export function beginTlsChecks(readSetupError: () => string | null, clear: () => void): void {
  problems.length = 0;
  if (readSetupError() === lastReported) clear(); // clearing a null error is harmless
  lastReported = null;
}

/**
 * The problems recorded since beginTlsChecks(), joined after `ahead` (the
 * ignored OTEL_METRICS_EXPORTER entries, which setup_error lists first), or
 * null when there were none.
 */
export function takeTlsProblems(ahead: readonly string[] = []): string | null {
  const joined = problems.length > 0 ? [...ahead, ...problems].join(SEPARATOR) : '';
  problems.length = 0;
  lastReported = joined || null;
  return lastReported;
}
