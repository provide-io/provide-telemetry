# React Helper Design — `@undef-games/telemetry/react`

**Date:** 2026-03-30  
**Status:** Approved

## Summary

Add a `./react` sub-export to `@undef-games/telemetry` that bridges React 18+ component lifecycle with the existing imperative telemetry API. Two exports only: `useTelemetryContext` and `TelemetryErrorBoundary`. React is a peer dependency — never bundled.

---

## Entry Point

**File:** `typescript/src/react.ts`  
**Export path:** `"./react"` in `package.json` exports map.

```json
"./react": {
  "types": "./dist/react.d.ts",
  "import": "./dist/react.js"
}
```

**Peer dependency added to `package.json`:**

```json
"react": ">=18"
```

---

## API Surface

### `useTelemetryContext(values: Record<string, unknown>): void`

Binds key/value pairs into telemetry context on mount; unbinds them on unmount. Re-runs when `values` changes (stable ref comparison to avoid infinite loops).

Calls `bindContext(values)` from the main package on mount/update, and `unbindContext(...keys)` on cleanup.

**Usage:**
```ts
// At app root after session is established
useTelemetryContext({ user_id: user.id, session_id: session.id, tenant: org.slug });
```

**Behaviour:**
- On mount: `bindContext(values)`
- On values change: unbind old keys, bind new values
- On unmount: `unbindContext(...Object.keys(values))`
- Stable ref guard: uses `useRef` + JSON comparison to avoid re-running on referentially-new-but-equal objects

---

### `TelemetryErrorBoundary`

A React class component (required by React for error boundaries). Catches render errors in its subtree, logs them unconditionally via `getLogger('react.error_boundary')`, and renders a fallback UI.

**Props:**
```ts
interface TelemetryErrorBoundaryProps {
  children: ReactNode;
  fallback: ReactNode | ((error: Error, reset: () => void) => ReactNode);
  onError?: (error: Error, info: React.ErrorInfo) => void;
}
```

**Behaviour:**
- `componentDidCatch(error, info)`: logs `error.message`, `error.stack`, and `info.componentStack` at error level; then calls `onError` prop if provided
- `render()`: if error caught, renders `fallback` (calls it as a function if it's a render prop, passing `error` and `reset`); otherwise renders `children`
- `reset()`: clears caught error state, re-renders children

**Usage:**
```tsx
<TelemetryErrorBoundary
  fallback={(error, reset) => (
    <div>
      <p>Something broke: {error.message}</p>
      <button onClick={reset}>Try again</button>
    </div>
  )}
  onError={(err, info) => myAlertService.notify(err, info)}
>
  <MyComponent />
</TelemetryErrorBoundary>
```

Plain `ReactNode` fallback also accepted:
```tsx
<TelemetryErrorBoundary fallback={<p>Something went wrong.</p>}>
  <MyComponent />
</TelemetryErrorBoundary>
```

---

## File Structure

```
typescript/src/
└── react.ts          # New file — useTelemetryContext + TelemetryErrorBoundary
```

No new test directories needed — tests mirror src structure:

```
typescript/tests/
└── react.test.tsx    # New file — vitest + happy-dom
```

---

## Testing

- `happy-dom` is already a dev dependency — no new deps needed for DOM/React rendering
- `@testing-library/react` added as dev dependency for component tests
- Tests cover: bind on mount, unbind on unmount, values change, error caught + logged, reset, render prop fallback, static node fallback, `onError` callback called

---

## Quality Constraints

Same as the rest of the package:
- 100% branch coverage
- mypy-equivalent: strict TypeScript (`noImplicitAny`, full annotations)
- SPDX header required
- File must stay under 500 LOC (trivially — this will be ~100 LOC)
- React peer dep must not appear in `dependencies`
