// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Bundle size check — reports source line count and dist/ size.
 */

import { readdirSync, statSync, readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const srcDir = join(import.meta.dirname ?? '.', '..', 'src');
const distDir = join(import.meta.dirname ?? '.', '..', 'dist');

// Count lines in src/**/*.ts
function countLines(dir: string): { files: number; lines: number } {
  let files = 0;
  let lines = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      const sub = countLines(full);
      files += sub.files;
      lines += sub.lines;
    } else if (entry.name.endsWith('.ts')) {
      files++;
      lines += readFileSync(full, 'utf-8').split('\n').length;
    }
  }
  return { files, lines };
}

// Sum bytes in dist/
function dirSize(dir: string): number {
  let total = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) total += dirSize(full);
    else total += statSync(full).size;
  }
  return total;
}

const src = countLines(srcDir);

console.log();
console.log('Bundle Size Report');
console.log(`  Source files:  ${src.files}`);
console.log(`  Source lines:  ${src.lines.toLocaleString()}`);

if (existsSync(distDir)) {
  const bytes = dirSize(distDir);
  console.log(`  Dist size:     ${(bytes / 1024).toFixed(1)} KB`);
} else {
  console.log('  Dist size:     (not built)');
}
console.log();

process.exit(0);
