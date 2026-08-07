// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

/**
 * Emit observed config metadata for the TypeScript SDK.
 *
 * The probe never reads spec/telemetry-api.yaml. Applicability is determined
 * differentially: build the config with a clean environment for the baseline,
 * then rebuild once per variable with that variable set. A variable this SDK
 * parses changes the config; one it ignores leaves it identical. The reported
 * default and type come from the baseline config object.
 *
 * No module-scope await — this file is run with `npx tsx`, whose default CJS
 * output rejects top-level await.
 */

import { configFromEnv } from '../../typescript/src/config-env.js';

// Values chosen to differ from every spec default, including valid values for
// validated fields (a rejected value proves the variable is read but leaves no
// config object to diff).
const PROBE_VALUES = [
  'DEBUG',
  'json',
  'red',
  '3',
  '1327',
  '0.4271',
  'probe-sentinel-value',
  'false',
  'true',
  'http://probe.invalid:4318',
  'probe-module=DEBUG',
  'probe-key=probe-value',
];

const OWNED_PREFIXES = ['PROVIDE_', 'OTEL_'];

type Entry = { type: string; default: string; applicable: boolean };

function cleanEnv(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v !== undefined && !OWNED_PREFIXES.some((p) => k.startsWith(p))) out[k] = v;
  }
  return out;
}

/**
 * Flatten a nested config object into dotted-path -> scalar.
 *
 * Arrays collapse to a joined string rather than staying arrays: `!==` on two
 * arrays is reference inequality, so every field would read as "changed" and
 * every variable as applicable, including ones the SDK has never heard of.
 */
function flatten(obj: unknown, prefix = ''): Record<string, unknown> {
  const flat: Record<string, unknown> = {};
  if (Array.isArray(obj)) {
    flat[prefix.replace(/\.$/, '')] = obj.map(String).join(',');
    return flat;
  }
  if (obj !== null && typeof obj === 'object') {
    for (const key of Object.keys(obj as Record<string, unknown>).sort()) {
      Object.assign(flat, flatten((obj as Record<string, unknown>)[key], `${prefix}${key}.`));
    }
    return flat;
  }
  flat[prefix.replace(/\.$/, '')] = obj;
  return flat;
}

function build(env: Record<string, string>): Record<string, unknown> {
  const saved = { ...process.env };
  for (const k of Object.keys(process.env)) delete process.env[k];
  Object.assign(process.env, env);
  try {
    return flatten(configFromEnv());
  } finally {
    for (const k of Object.keys(process.env)) delete process.env[k];
    Object.assign(process.env, saved);
  }
}

function typeName(value: unknown): string {
  if (typeof value === 'boolean') return 'bool';
  // JavaScript has one numeric type: 1.0 and 1 are indistinguishable at
  // runtime, so reporting 'int' for a value the spec calls 'float' would be a
  // guess. Report what is actually observable and let the comparator accept
  // 'number' wherever the spec says int or float.
  if (typeof value === 'number') return 'number';
  return 'str';
}

/**
 * Express a numeric default in the units the *environment variable* uses.
 *
 * TypeScript stores several durations in milliseconds behind a variable named
 * `..._TIMEOUT_SECONDS` (`exporterLogsTimeoutMs: 10000` for a 10-second
 * default). Reporting the field value would make the SDK look like it disagreed
 * with the spec when it agrees exactly. Rather than hardcoding which fields are
 * scaled, measure it: setting the variable to a known V and observing field
 * value F gives the SDK's own conversion factor F/V, which converts the
 * baseline back into variable units.
 */
function defaultInVariableUnits(baselineValue: unknown, probeValue: string, observedValue: unknown): unknown {
  if (typeof baselineValue !== 'number' || typeof observedValue !== 'number') return baselineValue;
  const probed = Number(probeValue);
  if (!Number.isFinite(probed) || probed === 0 || observedValue === 0) return baselineValue;
  const scale = observedValue / probed;
  // Only unit conversions are of interest; a scale of 1 means no conversion,
  // and a non-integral scale means the field is not a simple rescaling.
  if (scale === 1 || !Number.isInteger(scale) || scale <= 0) return baselineValue;
  return baselineValue / scale;
}

function render(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.map(String).join(',');
  return String(value);
}

function observe(envVars: string[]): Record<string, Entry> {
  const baseEnv = cleanEnv();
  const baseline = build(baseEnv);
  const entries: Record<string, Entry> = {};

  for (const envVar of envVars) {
    let settled = false;
    let rejected = false;
    for (const probeValue of PROBE_VALUES) {
      let observed: Record<string, unknown>;
      try {
        observed = build({ ...baseEnv, [envVar]: probeValue });
      } catch {
        rejected = true; // a rejected value still proves the variable is read
        continue;
      }
      const changed = Object.keys(baseline)
        .filter((k) => k in observed && observed[k] !== baseline[k])
        .sort();
      if (changed.length > 0) {
        const key = changed[0]!;
        entries[envVar] = {
          type: typeName(baseline[key]),
          default: render(defaultInVariableUnits(baseline[key], probeValue, observed[key])),
          applicable: true,
        };
        settled = true;
        break;
      }
      // A key the probe *added* counts too: an empty record contributes no
      // baseline keys, so shared-key comparison alone reads as "ignored".
      const added = Object.keys(observed).filter((k) => !(k in baseline));
      if (added.length > 0) {
        entries[envVar] = { type: 'str', default: '', applicable: true };
        settled = true;
        break;
      }
    }
    if (!settled) entries[envVar] = { type: '', default: '', applicable: rejected };
  }
  return entries;
}

const envVars = process.argv.slice(2);
if (envVars.length === 0) {
  process.stderr.write('usage: config_probe_typescript.ts ENV_VAR [ENV_VAR ...]\n');
  process.exit(2);
}
process.stdout.write(`${JSON.stringify({ language: 'typescript', entries: observe(envVars) })}\n`);
