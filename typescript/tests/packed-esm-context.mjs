// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Packed-artifact regression: scoped storage must survive publication.
//
// Run by ci/verify-npm-consumer-package.sh against the tarball-installed
// package, never against the working tree. The whole point is that vitest and
// tsx both load this package as CommonJS, where `require('node:async_hooks')`
// resolves and every isolation test passes — while the published package
// declares `"type": "module"`, where `require` is undefined. That gap shipped:
// context.ts and tracing.ts silently fell back to a single module-level store,
// so concurrent requests in a real consumer shared log context and trace IDs.
// Nothing but importing the installed package from Node can catch it.
//
// Timing is part of the contract too. These assertions run in the first
// microtasks after import, deliberately: a consumer that awaits the import and
// immediately serves a request must already have isolation, not acquire it a
// tick later.

import assert from 'node:assert/strict';

import {
  getContext,
  getTraceContext,
  isFallbackMode,
  runWithContext,
  withTrace,
} from '@provide-io/telemetry';

// 1. Concurrent scopes stay separate until their callbacks settle.
const seen = await Promise.all(
  ['a', 'b'].map((request_id) =>
    runWithContext({ request_id }, async () => {
      await Promise.resolve();
      return getContext().request_id;
    }),
  ),
);
assert.deepEqual(seen, ['a', 'b'], `concurrent log contexts crossed: ${JSON.stringify(seen)}`);

// 2. A rejecting inner scope restores its predecessor rather than clearing it.
await runWithContext({ request_id: 'outer' }, async () => {
  await assert.rejects(
    runWithContext({ request_id: 'inner' }, async () => {
      await Promise.resolve();
      throw new Error('boom');
    }),
    /boom/,
  );
  assert.equal(getContext().request_id, 'outer', 'rejection did not restore the outer context');
});

// 3. Trace IDs are per-flow, not per-process. withTrace synthesises IDs into
//    the tracing module's own scoped storage, which had the identical bug.
const traceIds = await Promise.all(
  ['one', 'two'].map((name) =>
    withTrace(`packed.${name}`, async () => {
      await Promise.resolve();
      return getTraceContext().trace_id;
    }),
  ),
);
assert.ok(traceIds[0], 'no trace id was assigned inside withTrace');
assert.notEqual(traceIds[0], traceIds[1], `concurrent flows shared a trace id: ${traceIds[0]}`);

// 4. The library must not believe it is in fallback mode in a plain Node ESM
//    consumer — that flag is what setupTelemetry fails loud on.
assert.equal(isFallbackMode(), false, 'packed ESM artifact reports AsyncLocalStorage unavailable');

console.log('OK: packed ESM artifact isolates log context and trace ids');
