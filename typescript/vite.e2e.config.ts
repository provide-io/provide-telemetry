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
import { defineConfig } from 'vite';

export default defineConfig({
  root: 'e2e-browser',
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
