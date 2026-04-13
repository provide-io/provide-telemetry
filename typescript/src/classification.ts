// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Data classification engine — strippable governance module.
 *
 * Registers a classification hook on the PII engine when rules are configured.
 * If this file is deleted, the PII engine runs unchanged (hook stays null).
 */

import { setClassificationHook } from './pii';

/** Data classification labels. */
export type DataClass = 'PUBLIC' | 'INTERNAL' | 'PII' | 'PHI' | 'PCI' | 'SECRET';

/** Maps a glob pattern to a DataClass label. */
export interface ClassificationRule {
  pattern: string;
  classification: DataClass;
}

/** Internal rule with pre-compiled RegExp to avoid re-compilation on every key check. */
interface _CompiledRule {
  compiled: RegExp;
  classification: DataClass;
}

/** Defines the action to take per DataClass. */
export interface ClassificationPolicy {
  PUBLIC: string;
  INTERNAL: string;
  PII: string;
  PHI: string;
  PCI: string;
  SECRET: string;
}

const _DEFAULT_POLICY: ClassificationPolicy = {
  PUBLIC: 'pass',
  INTERNAL: 'pass',
  PII: 'redact',
  PHI: 'drop',
  PCI: 'hash',
  SECRET: 'drop', // pragma: allowlist secret
};

// Stryker disable next-line ArrayDeclaration
const _rules: _CompiledRule[] = [];
// Stryker disable next-line ObjectLiteral: initial _policy is tested by default-policy test; Stryker's perTest coverage misattributes the test that checks all six fields
let _policy: ClassificationPolicy = { ..._DEFAULT_POLICY };

/**
 * Compile a glob pattern (supporting * wildcards) to a RegExp.
 * Only * is treated as a wildcard; all other regex special chars are escaped.
 * Called once at registration time, not on every key check.
 */
function _compileGlob(pattern: string): RegExp {
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(`^${escaped}$`);
}

/**
 * Register classification rules and install the classification hook on the PII engine.
 * Patterns are compiled to RegExp once here rather than on every key lookup.
 */
export function registerClassificationRules(rules: ClassificationRule[]): void {
  for (const rule of rules) {
    _rules.push({ compiled: _compileGlob(rule.pattern), classification: rule.classification });
  }
  setClassificationHook(_classifyField);
}

/** Replace the current classification policy. */
export function setClassificationPolicy(policy: ClassificationPolicy): void {
  _policy = { ...policy };
}

/** Return the current classification policy. */
export function getClassificationPolicy(): ClassificationPolicy {
  return { ..._policy };
}

/** Return the DataClass label for a key if a rule matches, else null. */
export function _classifyField(key: string, _value: unknown): string | null {
  for (const rule of _rules) {
    if (rule.compiled.test(key)) {
      return rule.classification;
    }
  }
  return null;
}

/** Reset all classification state and remove the hook (test helper). */
export function resetClassificationForTests(): void {
  _rules.length = 0;
  _policy = { ..._DEFAULT_POLICY };
  setClassificationHook(null);
}
