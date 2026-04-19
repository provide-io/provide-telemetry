// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Regression: propagation.ts must not contain a module-scope `await`
// statement. tsx/esbuild's CJS output forbids top-level await ("Top-level
// await is currently not supported with the cjs output format"), and the
// cross-language parity harness invokes TypeScript probes via `npx tsx`,
// which defaults to CJS output. A regression here breaks every TS
// runtime/contract probe at module-load time.

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import * as ts from 'typescript';
import { describe, it, expect } from 'vitest';

const PROPAGATION_PATH = resolve(__dirname, '../src/propagation.ts');

function findTopLevelAwaits(sourceFile: ts.SourceFile): ts.Node[] {
  const offenders: ts.Node[] = [];
  // Only walk DIRECT children of the source file. Anything nested inside a
  // function/class/IIFE is not module-scope.
  for (const stmt of sourceFile.statements) {
    visit(stmt);
  }
  return offenders;

  function visit(node: ts.Node): void {
    // Stop descent at any function-like or class boundary — those introduce a
    // new scope where `await` is legal (inside `async`).
    if (
      ts.isFunctionDeclaration(node) ||
      ts.isFunctionExpression(node) ||
      ts.isArrowFunction(node) ||
      ts.isMethodDeclaration(node) ||
      ts.isConstructorDeclaration(node) ||
      ts.isGetAccessor(node) ||
      ts.isSetAccessor(node) ||
      ts.isClassDeclaration(node) ||
      ts.isClassExpression(node)
    ) {
      return;
    }
    if (ts.isAwaitExpression(node)) {
      offenders.push(node);
    }
    ts.forEachChild(node, visit);
  }
}

describe('propagation.ts module-scope await regression', () => {
  it('contains no top-level await (would break tsx CJS output for parity probes)', () => {
    const source = readFileSync(PROPAGATION_PATH, 'utf8');
    const sf = ts.createSourceFile(
      'propagation.ts',
      source,
      ts.ScriptTarget.ES2022,
      /* setParentNodes */ true,
      ts.ScriptKind.TS,
    );
    const offenders = findTopLevelAwaits(sf);
    const lines = offenders.map((node) => {
      const { line, character } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
      return `line ${line + 1}, col ${character + 1}: ${node.getText(sf).slice(0, 80)}`;
    });
    expect(
      offenders,
      `propagation.ts must not have module-scope await — esbuild CJS output forbids it.\n` +
        `Wrap async work in an IIFE or call site instead.\nOffenders:\n  ${lines.join('\n  ')}`,
    ).toHaveLength(0);
  });
});
