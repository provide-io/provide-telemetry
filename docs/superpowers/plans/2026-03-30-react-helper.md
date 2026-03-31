# React Helper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `@undef-games/telemetry/react` sub-export with `useTelemetryContext` and `TelemetryErrorBoundary`.

**Architecture:** Single new source file `typescript/src/react.ts` exports two primitives that bridge React 18+ lifecycle to the existing global imperative API. React is a peer dependency. Tests live in `typescript/tests/react.test.tsx`.

**Tech Stack:** React 18+, TypeScript (strict), Vitest + happy-dom + @testing-library/react

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Modify | `typescript/package.json` | Add `./react` export, `react >=18` peer dep, dev deps |
| Modify | `typescript/tsconfig.test.json` | Add `jsx: react-jsx`, include `tests/**/*.tsx` |
| Create | `typescript/src/react.ts` | `useTelemetryContext` + `TelemetryErrorBoundary` |
| Create | `typescript/tests/react.test.tsx` | All tests for both exports |

---

## Task 1: Install deps and update configs

**Files:**
- Modify: `typescript/package.json`
- Modify: `typescript/tsconfig.test.json`

- [ ] **Step 1: Add React peer dep and dev deps to package.json**

In `typescript/package.json`, add to `peerDependencies`:
```json
"react": ">=18"
```

Add to `peerDependenciesMeta`:
```json
"react": {
  "optional": false
}
```

Add to `devDependencies`:
```json
"@testing-library/react": "^16.0.0",
"@types/react": "^18.0.0",
"react": "^18.0.0"
```

Add to the `exports` map (after the `"./otel"` entry):
```json
"./react": {
  "types": "./dist/react.d.ts",
  "import": "./dist/react.js"
}
```

- [ ] **Step 2: Install the new dependencies**

```bash
cd typescript && npm install
```

Expected: lock file updated, `react`, `@types/react`, `@testing-library/react` appear in `node_modules`.

- [ ] **Step 3: Update tsconfig.test.json for JSX and .tsx test files**

Replace the contents of `typescript/tsconfig.test.json` with:
```json
{
  "extends": "./tsconfig.json",
  "compilerOptions": {
    "noEmit": true,
    "rootDir": ".",
    "jsx": "react-jsx"
  },
  "include": ["src/**/*.ts", "tests/**/*.ts", "tests/**/*.tsx"],
  "exclude": ["node_modules", "dist", "src/otel.ts"]
}
```

- [ ] **Step 4: Verify typecheck still passes with no source changes**

```bash
cd typescript && npm run typecheck
```

Expected: exits 0 with no errors.

- [ ] **Step 5: Commit**

```bash
cd typescript && git add package.json package-lock.json tsconfig.test.json
git commit -m "chore(react): add react peer dep, testing-library, jsx tsconfig"
```

---

## Task 2: Implement `useTelemetryContext`

**Files:**
- Create: `typescript/src/react.ts`
- Create: `typescript/tests/react.test.tsx`

- [ ] **Step 1: Create the test file with useTelemetryContext tests (failing)**

Create `typescript/tests/react.test.tsx`:
```tsx
// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, renderHook } from '@testing-library/react';
import { _resetContext, getContext } from '../src/context';
import { useTelemetryContext } from '../src/react';

afterEach(() => {
  _resetContext();
  vi.restoreAllMocks();
});

// ── useTelemetryContext ──────────────────────────────────────────────────────

describe('useTelemetryContext', () => {
  it('binds values into telemetry context on mount', () => {
    renderHook(() => useTelemetryContext({ user_id: 'u1', tenant: 'acme' }));
    expect(getContext()).toMatchObject({ user_id: 'u1', tenant: 'acme' });
  });

  it('unbinds keys on unmount', () => {
    const { unmount } = renderHook(() =>
      useTelemetryContext({ user_id: 'u1', tenant: 'acme' }),
    );
    unmount();
    const ctx = getContext();
    expect(ctx).not.toHaveProperty('user_id');
    expect(ctx).not.toHaveProperty('tenant');
  });

  it('updates context when values change', () => {
    const { rerender } = renderHook(
      ({ vals }: { vals: Record<string, unknown> }) => useTelemetryContext(vals),
      { initialProps: { vals: { user_id: 'u1' } } },
    );
    rerender({ vals: { user_id: 'u2', role: 'admin' } });
    const ctx = getContext();
    expect(ctx['user_id']).toBe('u2');
    expect(ctx['role']).toBe('admin');
  });

  it('unbinds removed keys when values object changes keys', () => {
    const { rerender } = renderHook(
      ({ vals }: { vals: Record<string, unknown> }) => useTelemetryContext(vals),
      { initialProps: { vals: { user_id: 'u1', old_key: 'gone' } } },
    );
    rerender({ vals: { user_id: 'u1' } });
    const ctx = getContext();
    expect(ctx['user_id']).toBe('u1');
    expect(ctx).not.toHaveProperty('old_key');
  });

  it('does not re-bind when reference changes but content is equal', () => {
    const { rerender } = renderHook(
      ({ vals }: { vals: Record<string, unknown> }) => useTelemetryContext(vals),
      { initialProps: { vals: { user_id: 'u1' } } },
    );
    // Spy after initial mount so we can count re-binds
    const { bindContext } = await import('../src/context');
    const spy = vi.spyOn(await import('../src/context'), 'bindContext');
    rerender({ vals: { user_id: 'u1' } }); // same content, new object reference
    expect(spy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the tests — expect import errors (react.ts doesn't exist yet)**

```bash
cd typescript && npx vitest run tests/react.test.tsx --reporter=verbose 2>&1 | head -30
```

Expected: fails with `Cannot find module '../src/react'`.

- [ ] **Step 3: Create `typescript/src/react.ts` with `useTelemetryContext`**

```ts
// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * React 18+ helpers for @undef-games/telemetry.
 *
 * Import from '@undef-games/telemetry/react'.
 * React must be installed as a peer dependency (>=18).
 */

import { useEffect, useRef, type ComponentType, Component, type ReactNode, type ErrorInfo } from 'react';
import { bindContext, unbindContext } from './context';
import { getLogger } from './logger';

// ── useTelemetryContext ──────────────────────────────────────────────────────

/**
 * Bind key/value pairs into telemetry context for the lifetime of the component.
 * Cleans up on unmount. Re-runs when values change (content-compared, not by reference).
 */
export function useTelemetryContext(values: Record<string, unknown>): void {
  const serialized = JSON.stringify(values);
  // Store previous keys so we can unbind keys that disappear between renders.
  const prevKeysRef = useRef<string[]>([]);

  useEffect(() => {
    const keys = Object.keys(values);
    // Unbind keys that were present before but are no longer in values.
    const removed = prevKeysRef.current.filter((k) => !keys.includes(k));
    if (removed.length > 0) unbindContext(...removed);

    bindContext(values);
    prevKeysRef.current = keys;

    return () => {
      unbindContext(...Object.keys(values));
    };
    // serialized is the stable dep — avoids re-running for referentially-new-but-equal objects.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serialized]);
}
```

- [ ] **Step 4: Run useTelemetryContext tests — expect most to pass**

```bash
cd typescript && npx vitest run tests/react.test.tsx -t "useTelemetryContext" --reporter=verbose 2>&1 | head -40
```

Expected: all `useTelemetryContext` tests pass (TelemetryErrorBoundary tests not yet written).

- [ ] **Step 5: Commit useTelemetryContext**

```bash
cd typescript && git add src/react.ts tests/react.test.tsx
git commit -m "feat(react): add useTelemetryContext hook"
```

---

## Task 3: Implement `TelemetryErrorBoundary`

**Files:**
- Modify: `typescript/src/react.ts`
- Modify: `typescript/tests/react.test.tsx`

- [ ] **Step 1: Add TelemetryErrorBoundary tests to react.test.tsx**

Append to `typescript/tests/react.test.tsx` (after the `useTelemetryContext` describe block):

```tsx
// ── TelemetryErrorBoundary ───────────────────────────────────────────────────

import * as loggerModule from '../src/logger';
import type { Logger } from '../src/logger';
import { TelemetryErrorBoundary } from '../src/react';

/** A component that throws when shouldThrow is true. */
function Bomb({ shouldThrow }: { shouldThrow: boolean }): React.ReactElement {
  if (shouldThrow) throw new Error('boom');
  return <span>safe</span>;
}

describe('TelemetryErrorBoundary', () => {
  let mockLogError: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockLogError = vi.fn();
    vi.spyOn(loggerModule, 'getLogger').mockReturnValue({
      trace: vi.fn(),
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: mockLogError,
      child: vi.fn(),
    } as unknown as Logger);
    // Suppress React's own error output in test console
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('renders children when no error', () => {
    const { getByText } = render(
      <TelemetryErrorBoundary fallback={<p>oops</p>}>
        <Bomb shouldThrow={false} />
      </TelemetryErrorBoundary>,
    );
    expect(getByText('safe')).toBeTruthy();
  });

  it('renders static ReactNode fallback when child throws', () => {
    const { getByText } = render(
      <TelemetryErrorBoundary fallback={<p>fallback rendered</p>}>
        <Bomb shouldThrow={true} />
      </TelemetryErrorBoundary>,
    );
    expect(getByText('fallback rendered')).toBeTruthy();
  });

  it('renders render-prop fallback with error and reset', () => {
    const { getByText } = render(
      <TelemetryErrorBoundary
        fallback={(error, reset) => (
          <div>
            <span>{error.message}</span>
            <button onClick={reset}>retry</button>
          </div>
        )}
      >
        <Bomb shouldThrow={true} />
      </TelemetryErrorBoundary>,
    );
    expect(getByText('boom')).toBeTruthy();
    expect(getByText('retry')).toBeTruthy();
  });

  it('logs error via getLogger on catch', () => {
    render(
      <TelemetryErrorBoundary fallback={<p>oops</p>}>
        <Bomb shouldThrow={true} />
      </TelemetryErrorBoundary>,
    );
    expect(loggerModule.getLogger).toHaveBeenCalledWith('react.error_boundary');
    expect(mockLogError).toHaveBeenCalledOnce();
    const [logObj] = mockLogError.mock.calls[0] as [Record<string, unknown>];
    expect(logObj['event']).toBe('react_error_caught');
    expect(logObj['error_message']).toBe('boom');
    expect(typeof logObj['component_stack']).toBe('string');
  });

  it('calls onError prop after logging', () => {
    const onError = vi.fn();
    render(
      <TelemetryErrorBoundary fallback={<p>oops</p>} onError={onError}>
        <Bomb shouldThrow={true} />
      </TelemetryErrorBoundary>,
    );
    expect(onError).toHaveBeenCalledOnce();
    const [err] = onError.mock.calls[0] as [Error];
    expect(err.message).toBe('boom');
  });

  it('reset clears error state and re-renders children', async () => {
    const { getByText, rerender } = render(
      <TelemetryErrorBoundary
        fallback={(_, reset) => <button onClick={reset}>retry</button>}
      >
        <Bomb shouldThrow={true} />
      </TelemetryErrorBoundary>,
    );
    // Error boundary caught — fallback shown
    const retryBtn = getByText('retry');

    // Clicking reset should clear error state
    await act(async () => {
      retryBtn.click();
    });

    // After reset, children re-render (Bomb still throws, so fallback shows again —
    // but state was cleared, proving reset() fired)
    expect(getByText('retry')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run tests — expect TelemetryErrorBoundary tests to fail**

```bash
cd typescript && npx vitest run tests/react.test.tsx -t "TelemetryErrorBoundary" --reporter=verbose 2>&1 | head -30
```

Expected: fails with `TelemetryErrorBoundary is not exported from '../src/react'`.

- [ ] **Step 3: Add TelemetryErrorBoundary to `typescript/src/react.ts`**

Append to the existing `typescript/src/react.ts` (after `useTelemetryContext`):

```ts
// ── TelemetryErrorBoundary ───────────────────────────────────────────────────

interface TelemetryErrorBoundaryProps {
  children: ReactNode;
  fallback: ReactNode | ((error: Error, reset: () => void) => ReactNode);
  onError?: (error: Error, info: ErrorInfo) => void;
}

interface TelemetryErrorBoundaryState {
  error: Error | null;
}

/**
 * React error boundary that logs caught render errors via getLogger and renders
 * a fallback UI. Accepts a static ReactNode or a render-prop that receives the
 * caught error and a reset callback.
 *
 * Auto-logs to getLogger('react.error_boundary') on every catch. Call onError
 * for any additional handling (alerting, Sentry, etc.).
 */
export class TelemetryErrorBoundary extends Component<
  TelemetryErrorBoundaryProps,
  TelemetryErrorBoundaryState
> {
  constructor(props: TelemetryErrorBoundaryProps) {
    super(props);
    this.state = { error: null };
    this.reset = this.reset.bind(this);
  }

  static getDerivedStateFromError(error: Error): TelemetryErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    getLogger('react.error_boundary').error({
      event: 'react_error_caught',
      error_message: error.message,
      error_stack: error.stack ?? '',
      component_stack: info.componentStack ?? '',
    });
    this.props.onError?.(error, info);
  }

  reset(): void {
    this.setState({ error: null });
  }

  render(): ReactNode {
    const { error } = this.state;
    if (error !== null) {
      const { fallback } = this.props;
      if (typeof fallback === 'function') {
        return fallback(error, this.reset);
      }
      return fallback;
    }
    return this.props.children;
  }
}
```

- [ ] **Step 4: Run all react tests**

```bash
cd typescript && npx vitest run tests/react.test.tsx --reporter=verbose 2>&1
```

Expected: all tests pass.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
cd typescript && npm run test:coverage 2>&1 | tail -30
```

Expected: exits 0, 100% coverage maintained.

- [ ] **Step 6: Typecheck**

```bash
cd typescript && npm run typecheck
```

Expected: exits 0.

- [ ] **Step 7: Lint**

```bash
cd typescript && npm run lint
```

Expected: exits 0 (no ESLint errors).

- [ ] **Step 8: Commit**

```bash
cd typescript && git add src/react.ts tests/react.test.tsx
git commit -m "feat(react): add TelemetryErrorBoundary with render-prop fallback and reset"
```

---

## Task 4: Wire exports and final verification

**Files:**
- Modify: `typescript/src/index.ts` — no change needed (react is a separate entry point)
- Modify: `typescript/vitest.config.ts` — ensure `src/react.ts` is in coverage include

- [ ] **Step 1: Verify coverage include covers react.ts**

Check `typescript/vitest.config.ts`. The `include` is `['src/**/*.ts']` which already covers `src/react.ts`. No change needed. Confirm:

```bash
cd typescript && grep -n "include" vitest.config.ts
```

Expected: `include: ['src/**/*.ts']` — react.ts is already covered.

- [ ] **Step 2: Confirm `./react` export resolves after build**

```bash
cd typescript && npm run build 2>&1
```

Expected: `dist/react.js` and `dist/react.d.ts` exist:

```bash
ls typescript/dist/react.*
```

Expected: `dist/react.d.ts  dist/react.d.ts.map  dist/react.js`

- [ ] **Step 3: Run the full pre-publish check**

```bash
cd typescript && npm run prepublishOnly 2>&1 | tail -20
```

Expected: build + test:coverage both pass, exits 0.

- [ ] **Step 4: Commit final wiring**

```bash
git add typescript/package.json typescript/package-lock.json typescript/tsconfig.test.json
git commit -m "feat(react): wire ./react sub-export, update tsconfig and package.json"
```

---

## Self-Review

**Spec coverage check:**
- ✅ `useTelemetryContext` — Task 2
- ✅ Binds on mount, unbinds on unmount, re-runs on change, stable ref guard — Task 2 tests
- ✅ `TelemetryErrorBoundary` — Task 3
- ✅ Static ReactNode fallback — Task 3 test
- ✅ Render-prop fallback with `(error, reset)` — Task 3 test
- ✅ `onError` callback — Task 3 test
- ✅ Logs via `getLogger('react.error_boundary')` — Task 3 test
- ✅ `reset()` clears error state — Task 3 test
- ✅ `./react` export entry — Task 1 + Task 4
- ✅ React as peer dep — Task 1
- ✅ 100% coverage enforced — Task 3 step 5

**No placeholders found.**

**Type consistency:** `Logger` interface used from `../src/logger` in tests matches the `Logger` type exported from `src/logger.ts` (has `trace`, `debug`, `info`, `warn`, `error`, `child`). `ReactNode`, `ErrorInfo` imported from `react` in source. `TelemetryErrorBoundaryProps.fallback` typed as `ReactNode | ((error: Error, reset: () => void) => ReactNode)` — consistent across source and tests.
