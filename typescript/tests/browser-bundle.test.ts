// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * The browser build never reaches the Prometheus listener or Node's network
 * modules: browser TypeScript is Tier 1 only (prometheus_metrics in the spec).
 *
 * Bundles each browser-reachable entry point with esbuild for the browser
 * platform and inspects what the bundle pulled in. Any static path to
 * prom-listener.ts or a node:http / node:https / node:tls import fails here.
 */

import { resolve } from 'node:path';
import { build, type Metafile } from 'esbuild';
import { describe, expect, it } from 'vitest';

const ROOT = resolve(__dirname, '..');
const FORBIDDEN_MODULES = ['node:http', 'node:https', 'node:tls', 'node:net', 'bcryptjs', 'yaml'];

async function browserBundle(entry: string): Promise<Metafile> {
  const result = await build({
    entryPoints: [resolve(ROOT, entry)],
    absWorkingDir: ROOT,
    bundle: true,
    platform: 'browser',
    format: 'esm',
    write: false,
    metafile: true,
    logLevel: 'silent',
    // Peers are the consumer's bundler's business, and node:* stays external so a
    // forbidden built-in shows up as an import below rather than as a build error.
    external: ['@opentelemetry/*', 'pino', 'react', 'node:*'],
  });
  return result.metafile;
}

function imported(metafile: Metafile): string[] {
  return Object.values(metafile.outputs).flatMap((o) => o.imports.map((i) => i.path));
}

describe('browser bundle', () => {
  for (const entry of ['src/index.ts', 'src/otel-noop.ts']) {
    it(`${entry} excludes the listener and Node network modules`, async () => {
      const metafile = await browserBundle(entry);
      const inputs = Object.keys(metafile.inputs);
      expect(inputs.some((i) => i.endsWith('src/prom-listener.ts'))).toBe(false);
      expect(inputs.some((i) => i.endsWith('src/prometheus.ts'))).toBe(false);
      for (const forbidden of FORBIDDEN_MODULES)
        expect(imported(metafile)).not.toContain(forbidden);
    }, 30_000);
  }

  it('the check would notice the listener', async () => {
    const metafile = await browserBundle('src/prom-listener.ts');
    expect(imported(metafile)).toContain('node:http');
    expect(Object.keys(metafile.inputs).some((i) => i.endsWith('src/prom-listener.ts'))).toBe(true);
  }, 30_000);
});
