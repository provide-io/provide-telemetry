// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: AGPL-3.0-or-later

import * as fc from 'fast-check';
import { afterEach, describe, it } from 'vitest';
import { _resetConfig, configFromEnv } from '../../src/config';

afterEach(() => _resetConfig());

describe('property: configFromEnv()', () => {
  it('always produces a valid TelemetryConfig without throwing', () => {
    fc.assert(
      fc.property(
        fc.record({
          UNDEF_LOG_LEVEL: fc.oneof(fc.constant(undefined), fc.string({ maxLength: 20 })),
          UNDEF_LOG_FORMAT: fc.oneof(
            fc.constant(undefined),
            fc.constant('json'),
            fc.constant('pretty'),
            fc.string({ maxLength: 10 }),
          ),
          UNDEF_TRACE_ENABLED: fc.oneof(
            fc.constant(undefined),
            fc.constant('true'),
            fc.constant('false'),
          ),
        }),
        (envVars) => {
          const saved: Record<string, string | undefined> = {};
          for (const [k, v] of Object.entries(envVars)) {
            saved[k] = process.env[k];
            if (v === undefined) delete process.env[k];
            else process.env[k] = v;
          }
          try {
            const cfg = configFromEnv();
            // logFormat must be 'json' or 'pretty'
            if (cfg.logFormat !== 'json' && cfg.logFormat !== 'pretty') return false;
            // logLevel must be lowercase
            if (cfg.logLevel !== cfg.logLevel.toLowerCase()) return false;
            // otelEnabled must be boolean
            if (typeof cfg.otelEnabled !== 'boolean') return false;
            return true;
          } finally {
            for (const [k, v] of Object.entries(saved)) {
              if (v === undefined) delete process.env[k];
              else process.env[k] = v;
            }
          }
        },
      ),
    );
  });

  it('logFormat is always json or pretty', () => {
    fc.assert(
      fc.property(fc.boolean(), (useJson) => {
        process.env['UNDEF_LOG_FORMAT'] = useJson ? 'json' : 'pretty';
        const cfg = configFromEnv();
        delete process.env['UNDEF_LOG_FORMAT'];
        return cfg.logFormat === 'json' || cfg.logFormat === 'pretty';
      }),
    );
  });

  it('otelEnabled is always boolean', () => {
    fc.assert(
      fc.property(
        fc.oneof(fc.constant('true'), fc.constant('false'), fc.constant('')),
        (val) => {
          process.env['UNDEF_TRACE_ENABLED'] = val;
          const cfg = configFromEnv();
          delete process.env['UNDEF_TRACE_ENABLED'];
          return typeof cfg.otelEnabled === 'boolean';
        },
      ),
    );
  });

  it('logLevel is always lowercase', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('INFO', 'DEBUG', 'WARN', 'error', 'trace'),
        (level) => {
          process.env['UNDEF_LOG_LEVEL'] = level;
          const cfg = configFromEnv();
          delete process.env['UNDEF_LOG_LEVEL'];
          return cfg.logLevel === cfg.logLevel.toLowerCase();
        },
      ),
    );
  });
});
