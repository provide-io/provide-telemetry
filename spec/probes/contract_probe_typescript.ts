// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// SPDX-Comment: Part of provide-telemetry.

/**
 * Contract probe interpreter for TypeScript.
 * Reads a case from spec/contract_fixtures.yaml, executes each step using
 * the real public API, and emits JSON output for cross-language comparison.
 */

import process from 'node:process';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const tsRequire = createRequire(resolve(__dirname, '..', '..', 'typescript', 'node_modules'));
// eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
const YAML: { parse: (s: string) => unknown } = tsRequire('yaml');

import {
  setupTelemetry,
  shutdownTelemetry,
  resetTelemetryState,
  getLogger,
  bindContext,
  extractW3cContext,
  bindPropagationContext,
  clearPropagationContext,
  getTraceContext,
  getRuntimeStatus,
  getRuntimeConfig,
} from '../../typescript/src/index.js';

// ── Types ────────────────────────────────────────────────────────────────────

interface Step {
  op: string;
  into?: string;
  message?: string;
  fields?: Record<string, unknown>;
  traceparent?: string;
  baggage?: string;
  overrides?: Record<string, unknown>;
}

interface ContractCase {
  description: string;
  steps: Step[];
  expect: Record<string, unknown>;
}

interface FixtureFile {
  contract_cases: Record<string, ContractCase>;
}

// ── Log capture ──────────────────────────────────────────────────────────────

let capturedRecords: Record<string, unknown>[] = [];
const origLog = console.log;
const origWarn = console.warn;
const origError = console.error;

function installCapture(): void {
  capturedRecords = [];
  // The pino logger emits JSON via console.log (level 30 maps to "log").
  console.log = (...args: unknown[]) => {
    for (const arg of args) {
      if (typeof arg === 'string') {
        try {
          capturedRecords.push(JSON.parse(arg) as Record<string, unknown>);
        } catch {
          // not JSON — ignore
        }
      }
    }
  };
  // Suppress warning/error noise from the library.
  console.warn = () => {};
  console.error = () => {};
}

function restoreConsole(): void {
  console.log = origLog;
  console.warn = origWarn;
  console.error = origError;
}

// ── Step executors ───────────────────────────────────────────────────────────

function execSetup(step: Step): void {
  const overrides: Record<string, unknown> = {
    consoleOutput: true,
    logFormat: 'json',
    ...(step.overrides ?? {}),
  };
  setupTelemetry(overrides);
}

function execSetupInvalid(step: Step): { raised: boolean; error: string } {
  try {
    setupTelemetry(step.overrides ?? {});
    return { raised: false, error: '' };
  } catch (err: unknown) {
    return {
      raised: true,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

async function execShutdown(): Promise<void> {
  await shutdownTelemetry();
}

function execBindPropagation(step: Step): void {
  const headers: Record<string, string> = {};
  if (step.traceparent) headers['traceparent'] = step.traceparent;
  if (step.baggage) headers['baggage'] = step.baggage;
  const ctx = extractW3cContext(headers);
  bindPropagationContext(ctx);
}

function execClearPropagation(): void {
  clearPropagationContext();
}

function execBindContext(step: Step): void {
  if (step.fields) {
    bindContext(step.fields as Record<string, string>);
  }
}

function execEmitLog(step: Step): void {
  const logger = getLogger('contract');
  logger.info(step.fields ?? {}, step.message ?? '');
}

function execCaptureLog(): Record<string, unknown> {
  if (capturedRecords.length === 0) {
    return {};
  }
  return capturedRecords[capturedRecords.length - 1];
}

function execGetTraceContext(): Record<string, unknown> {
  const ctx = getTraceContext();
  return {
    trace_id: ctx.trace_id ?? '',
    span_id: ctx.span_id ?? '',
  };
}

function execGetRuntimeStatus(): Record<string, unknown> {
  const status = getRuntimeStatus();
  const config = getRuntimeConfig();
  return {
    active: status.setupDone,
    service_name: config.serviceName,
  };
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main(): Promise<void> {
  const caseId = process.env['PROVIDE_CONTRACT_CASE'];
  if (!caseId) {
    throw new Error('PROVIDE_CONTRACT_CASE env var is required');
  }

  const fixturesPath = resolve(__dirname, '..', 'contract_fixtures.yaml');
  const raw = readFileSync(fixturesPath, 'utf-8');
  const fixtures = YAML.parse(raw) as FixtureFile;
  const testCase = fixtures.contract_cases[caseId];
  if (!testCase) {
    throw new Error(`unknown contract case: ${caseId}`);
  }

  resetTelemetryState();
  installCapture();

  const variables: Record<string, unknown> = {};

  try {
    for (const step of testCase.steps) {
      switch (step.op) {
        case 'setup':
          execSetup(step);
          break;
        case 'setup_invalid': {
          const result = execSetupInvalid(step);
          if (step.into) variables[step.into] = result;
          break;
        }
        case 'shutdown':
          await execShutdown();
          break;
        case 'bind_propagation':
          execBindPropagation(step);
          break;
        case 'clear_propagation':
          execClearPropagation();
          break;
        case 'bind_context':
          execBindContext(step);
          break;
        case 'emit_log':
          execEmitLog(step);
          break;
        case 'capture_log': {
          const record = execCaptureLog();
          if (step.into) variables[step.into] = record;
          break;
        }
        case 'get_trace_context': {
          const ctx = execGetTraceContext();
          if (step.into) variables[step.into] = ctx;
          break;
        }
        case 'get_runtime_status': {
          const status = execGetRuntimeStatus();
          if (step.into) variables[step.into] = status;
          break;
        }
        default:
          throw new Error(`unsupported op: ${step.op}`);
      }
    }
  } finally {
    restoreConsole();
    resetTelemetryState();
  }

  // Use origLog to emit output (console.log is restored but be explicit)
  origLog(JSON.stringify({ case: caseId, variables }));
}

void main();
