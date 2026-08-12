// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
/**
 * Vite config for the browser E2E test.
 *
 * Two proxies eliminate CORS:
 *   /v1      → OpenObserve OTLP endpoint (trace export)
 *   /backend → Python test backend (traced fetch), path prefix stripped
 *
 * Env vars consumed at startup:
 *   E2E_OTLP_ENDPOINT   — OTLP base URL  (e.g. http://localhost:5080/api/default)
 *   E2E_BACKEND_PORT    — Python backend port (e.g. 18765)
 */
import { defineConfig, type Plugin } from 'vite';

// Every optional peer dep that src/otel-dynimport.ts may load at runtime.
// Keep in sync with the dynImportOtel() call sites in src/.
const OTEL_PEER_DEPS = [
  '@opentelemetry/api-logs',
  '@opentelemetry/context-async-hooks',
  '@opentelemetry/exporter-logs-otlp-http',
  '@opentelemetry/exporter-metrics-otlp-http',
  '@opentelemetry/exporter-trace-otlp-http',
  '@opentelemetry/resources',
  '@opentelemetry/sdk-logs',
  '@opentelemetry/sdk-metrics',
  '@opentelemetry/sdk-trace-base',
];

// dynImportOtel() routes optional imports through a *variable* specifier so
// bundlers cannot statically resolve them (see src/otel-dynimport.ts). That
// also defeats Vite's dev-server import rewriting, so the browser receives a
// bare specifier it cannot resolve and OTel setup silently no-ops. For the
// E2E page only, replace the module body with a literal-specifier switch that
// Vite can rewrite and prebundle.
function dynImportShim(): Plugin {
  const cases = OTEL_PEER_DEPS.map(
    (pkg) => `    case '${pkg}': return import('${pkg}');`,
  ).join('\n');
  return {
    name: 'e2e-otel-dynimport-shim',
    enforce: 'pre',
    transform(_code: string, id: string) {
      if (!id.replace(/\?.*$/, '').endsWith('/src/otel-dynimport.ts')) {
        return null;
      }
      return [
        '// eslint-disable-next-line @typescript-eslint/no-explicit-any',
        'export function dynImportOtel(pkg: string): Promise<any> {',
        '  switch (pkg) {',
        cases,
        '    default:',
        "      return Promise.reject(new Error(`unshimmed optional dep: ${pkg}`));",
        '  }',
        '}',
        '',
      ].join('\n');
    },
  };
}

export default defineConfig({
  root: 'e2e-browser',
  plugins: [dynImportShim()],
  server: {
    host: '127.0.0.1',
    fs: {
      // Allow Vite to serve files from typescript/ (parent of e2e-browser/).
      allow: ['..'],
    },
    proxy: {
      '/v1': {
        target: process.env['E2E_OTLP_ENDPOINT'] ?? 'http://localhost:5080/api/default',
        changeOrigin: true,
      },
      '/backend': {
        target: `http://127.0.0.1:${process.env['E2E_BACKEND_PORT'] ?? '18765'}`,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/backend/, ''),
      },
    },
  },
});
