# @undef/telemetry

Structured logging + OpenTelemetry traces and metrics for TypeScript — feature parity with the [`undef-telemetry`](https://pypi.org/p/undef-telemetry) Python package.

## Install

```bash
npm install @undef/telemetry
```

### Optional OTEL peer dependencies

To export traces and metrics to an OTLP endpoint (e.g. OpenObserve, Jaeger, Tempo):

```bash
npm install \
  @opentelemetry/sdk-trace-base \
  @opentelemetry/sdk-metrics \
  @opentelemetry/resources \
  @opentelemetry/exporter-trace-otlp-http \
  @opentelemetry/exporter-metrics-otlp-http
```

All five are optional — the library degrades gracefully to no-op providers when they are absent.

## Quick start

```typescript
import { setupTelemetry, getConfig, getLogger, registerOtelProviders, shutdownTelemetry } from '@undef-games/telemetry';

// Call once at app startup.
setupTelemetry({
  serviceName: 'my-app',
  environment: 'production',
  version: '1.0.0',
  logLevel: 'info',
  logFormat: 'json',
  otelEnabled: true,
  otlpEndpoint: 'http://localhost:4318',
  otlpHeaders: { Authorization: 'Basic ...' },
});

// Activate OTLP exporters (requires peer deps above).
await registerOtelProviders(getConfig());

const log = getLogger('api');
log.info({ event: 'request.received.ok', method: 'GET', path: '/health', status: 200 });

// On shutdown — flushes and drains all OTel providers.
await shutdownTelemetry();
```

## API reference

### Setup

| Export | Description |
|--------|-------------|
| `setupTelemetry(config)` | Configure the library. Idempotent — safe to call multiple times. |
| `getConfig()` | Return the current `TelemetryConfig`. |
| `configFromEnv()` | Build config from environment variables (see [Configuration](#configuration)). |
| `registerOtelProviders(cfg)` | Wire OTLP trace + metrics exporters. Call after `setupTelemetry`. |
| `shutdownTelemetry()` | Flush and shut down all registered OTel providers. |

### Logging

```typescript
import { getLogger } from '@undef/telemetry';

const log = getLogger('my-module');
log.debug({ event: 'cache.miss.ok', key: 'user:42' });
log.info({ event: 'request.complete.ok', status: 200, duration_ms: 14 });
log.warn({ event: 'retry.attempt.warn', attempt: 2 });
log.error({ event: 'db.query.error', error: err.message });
```

Event names follow the DA(R)S pattern: 3 segments (`domain.action.status`) or 4 segments (`domain.action.resource.status`).

### Tracing

```typescript
import { withTrace, getActiveTraceIds, setTraceContext } from '@undef/telemetry';

const result = await withTrace('my.operation.ok', async () => {
  const { trace_id, span_id } = getActiveTraceIds();
  // trace_id / span_id are available here and in any log emitted inside
  return doWork();
});
```

### Metrics

```typescript
import { counter, gauge, histogram } from '@undef/telemetry';

const requests = counter('http.requests', { unit: '1', description: 'Total HTTP requests' });
requests.add(1, { method: 'GET', status: '200' });

const latency = histogram('http.duration', { unit: 'ms' });
latency.record(42, { route: '/api/users' });
```

### Context binding

```typescript
import { bindContext, runWithContext, clearContext } from '@undef/telemetry';

bindContext({ request_id: 'req-abc', user_id: 7 });
// All log calls in this async context will include these fields automatically.
clearContext();

// Scoped — context is automatically cleaned up after fn resolves.
await runWithContext({ trace_id: '...' }, async () => { /* ... */ });
```

### Session correlation

```typescript
import { bindSessionContext, getSessionId, clearSessionContext } from '@undef-games/telemetry';

bindSessionContext('sess-abc-123');
// All logs and traces now include session_id automatically.
const sid = getSessionId(); // 'sess-abc-123'
clearSessionContext();
```

### Error fingerprinting

```typescript
import { computeErrorFingerprint } from '@undef-games/telemetry';

try {
  throw new Error('connection refused');
} catch (e) {
  const err = e as Error;
  const fp = computeErrorFingerprint(err.constructor.name, err.stack);
  // fp: 12-char hex digest, stable across deploys — use for dedup and alert grouping.
}
```

### W3C trace propagation

```typescript
import { extractW3cContext, bindPropagationContext } from '@undef/telemetry';

// In an HTTP handler — extract incoming traceparent/tracestate.
const ctx = extractW3cContext(req.headers);
bindPropagationContext(ctx);
```

### PII sanitization

```typescript
import { sanitize, registerPiiRule } from '@undef/telemetry';

// Built-in: redacts password, token, secret, authorization, api_key, ...
const obj = { user: 'alice', password: 'hunter2' }; // pragma: allowlist secret
sanitize(obj);
// obj is now { user: 'alice', password: '[REDACTED]' }

// Custom rule (dot-separated path; '*' as wildcard segment)
registerPiiRule({ path: 'user.ssn', mode: 'redact' });
```

### Health snapshot

```typescript
import { getHealthSnapshot } from '@undef/telemetry';

const snap = getHealthSnapshot();
// snap.exportFailuresLogs, snap.tracesDropped, ...
```

### Runtime inspection

```typescript
import { getRuntimeConfig, getRuntimeStatus } from '@provide-io/telemetry';

const cfg = getRuntimeConfig();
const status = getRuntimeStatus();

console.log(cfg.serviceName);
console.log(status.setupDone, status.providers.traces, status.fallback.logs);
```

Use `getRuntimeConfig()` after setup or runtime reloads to inspect the applied
snapshot, and `getRuntimeStatus()` to see provider install state, fallback
mode, and the last setup error without reading internal modules.

## React integration

Requires React 18+ as a peer dependency.

```typescript
import { useTelemetryContext, TelemetryErrorBoundary } from '@provide-io/telemetry/react';
```

### `useTelemetryContext(values)`

Binds key/value pairs into telemetry context for the lifetime of a component. Automatically cleans up on unmount and re-runs when values change (compared by content, not reference).

```tsx
function UserDashboard({ userId }: { userId: string }) {
  useTelemetryContext({ user_id: userId, page: 'dashboard' });
  return <Dashboard />;
}
```

### `TelemetryErrorBoundary`

React error boundary that auto-logs caught render errors via `getLogger('react.error_boundary')`. Accepts a static fallback or a render-prop receiving the error and a reset callback.

```tsx
<TelemetryErrorBoundary
  fallback={(error, reset) => <ErrorPage error={error} onRetry={reset} />}
  onError={(error, info) => reportToSentry(error, info)}
>
  <App />
</TelemetryErrorBoundary>
```

## Browser support

The library is browser-compatible via conditional exports. OpenTelemetry providers become no-ops in browser environments, so no server-only imports leak into client bundles. No polyfills are required for modern browsers (ES2020+).

Browser-specific options in `setupTelemetry()`:

| Option | Effect |
|--------|--------|
| `captureToWindow: true` | Buffers structured logs to `window.__pinoLogs` for devtools inspection |
| `consoleOutput: true` | Mirrors log output to `console.debug` / `console.log` / `console.warn` / `console.error` |

## Configuration

All options can be set programmatically via `setupTelemetry()` or via environment variables:

| Env var | Default | Description |
|---------|---------|-------------|
| `PROVIDE_TELEMETRY_SERVICE_NAME` | `provide-service` | Service identity |
| `PROVIDE_TELEMETRY_ENV` | `development` | Deployment environment (fallback: `PROVIDE_ENV`) |
| `PROVIDE_TELEMETRY_VERSION` | `unknown` | Service version (fallback: `PROVIDE_VERSION`) |
| `PROVIDE_LOG_LEVEL` | `info` | Log level: `debug` / `info` / `warn` / `error` |
| `PROVIDE_LOG_FORMAT` | `json` | Output format: `json` / `pretty` |
| `PROVIDE_TRACE_ENABLED` | `false` | Enable OTLP export |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP base endpoint |
| `OTEL_EXPORTER_OTLP_HEADERS` | — | Comma-separated `key=value` auth headers |

### Pretty renderer

Set `logFormat: 'pretty'` (or `UNDEF_LOG_FORMAT=pretty`) for human-readable colored output during local development. Color support respects `FORCE_COLOR` and `NO_COLOR` environment variables.

```typescript
setupTelemetry({ logFormat: 'pretty' });
```

## Requirements

- Node.js ≥ 18
- TypeScript ≥ 5 (built with TypeScript 6)

## License

Apache-2.0. See [LICENSE](../LICENSES/Apache-2.0.txt).
