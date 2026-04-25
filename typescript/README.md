# @provide-io/telemetry

Structured logging + OpenTelemetry traces and metrics for TypeScript — feature parity with the [`provide-telemetry`](https://pypi.org/p/provide-telemetry) Python package.

## Install

```bash
npm install @provide-io/telemetry
```

### Optional OTEL peer dependencies

To export traces, metrics, and logs to an OTLP endpoint (e.g. OpenObserve, Jaeger, Tempo):

```bash
npm install \
  @opentelemetry/sdk-trace-base \
  @opentelemetry/sdk-metrics \
  @opentelemetry/sdk-logs \
  @opentelemetry/resources \
  @opentelemetry/exporter-trace-otlp-http \
  @opentelemetry/exporter-metrics-otlp-http \
  @opentelemetry/exporter-logs-otlp-http \
  @opentelemetry/api-logs
```

All eight are optional — the library degrades gracefully to no-op providers when they are absent.

## Quick start

```typescript
import { setupTelemetry, getConfig, getLogger, registerOtelProviders, shutdownTelemetry } from '@provide-io/telemetry';

// Call once at app startup.
setupTelemetry({
  serviceName: 'my-app',
  environment: 'production',
  version: '1.0.0',
  logLevel: 'info',
  logFormat: 'json',
  otelEnabled: true,
  tracingEnabled: true,
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
| `registerOtelProviders(cfg)` | Wire OTLP log, trace, and metric exporters for the signals enabled in config. Call after `setupTelemetry`. |
| `shutdownTelemetry()` | Flush and shut down all registered OTel providers. |

### Logging

```typescript
import { getLogger } from '@provide-io/telemetry';

const log = getLogger('my-module');
log.debug({ event: 'cache.miss.ok', key: 'user:42' });
log.info({ event: 'request.complete.ok', status: 200, duration_ms: 14 });
log.warn({ event: 'retry.attempt.warn', attempt: 2 });
log.error({ event: 'db.query.error', error: err.message });
```

Event names follow the DA(R)S pattern: 3 segments (`domain.action.status`) or 4 segments (`domain.action.resource.status`).

### Tracing

```typescript
import { withTrace, getActiveTraceIds, setTraceContext } from '@provide-io/telemetry';

const result = await withTrace('my.operation.ok', async () => {
  const { trace_id, span_id } = getActiveTraceIds();
  // trace_id / span_id are available here and in any log emitted inside
  return doWork();
});
```

### Metrics

```typescript
import { counter, gauge, histogram } from '@provide-io/telemetry';

const requests = counter('http.requests', { unit: '1', description: 'Total HTTP requests' });
requests.add(1, { method: 'GET', status: '200' });

const latency = histogram('http.duration', { unit: 'ms' });
latency.record(42, { route: '/api/users' });
```

### Context binding

```typescript
import { bindContext, runWithContext, clearContext } from '@provide-io/telemetry';

bindContext({ request_id: 'req-abc', user_id: 7 });
// All log calls in this async context will include these fields automatically.
clearContext();

// Scoped — context is automatically cleaned up after fn resolves.
await runWithContext({ trace_id: '...' }, async () => { /* ... */ });
```

### Session correlation

```typescript
import { bindSessionContext, getSessionId, clearSessionContext } from '@provide-io/telemetry';

bindSessionContext('sess-abc-123');
// All logs and traces now include session_id automatically.
const sid = getSessionId(); // 'sess-abc-123'
clearSessionContext();
```

### Error fingerprinting

```typescript
import { computeErrorFingerprint } from '@provide-io/telemetry';

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
import { extractW3cContext, bindPropagationContext } from '@provide-io/telemetry';

// In an HTTP handler — extract incoming traceparent/tracestate.
const ctx = extractW3cContext(req.headers);
bindPropagationContext(ctx);
```

### PII sanitization

```typescript
import { sanitize, registerPiiRule } from '@provide-io/telemetry';

// Built-in: redacts password, token, secret, authorization, api_key, ...
const obj = { user: 'alice', password: 'hunter2' }; // pragma: allowlist secret
sanitize(obj);
// obj is now { user: 'alice', password: '[REDACTED]' }

// Custom rule (dot-separated path; '*' as wildcard segment)
registerPiiRule({ path: 'user.ssn', mode: 'redact' });
```

### Health snapshot

```typescript
import { getHealthSnapshot } from '@provide-io/telemetry';

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
snapshot, and `getRuntimeStatus()` to see signal enablement, provider install
state, fallback mode, and the last setup error without reading internal
modules.

### Runtime reconfiguration

Use `reconfigureTelemetry()` to change config at runtime without a process
restart. It merges a partial `TelemetryConfig` over the current one and
re-runs `setupTelemetry()` with the result, rebuilding the logger so fresh
calls to `getLogger()` observe the new config.

```typescript
import { reconfigureTelemetry, getRuntimeConfig } from '@provide-io/telemetry';

// Rotate to a new OTLP collector endpoint mid-flight.
reconfigureTelemetry({
  otlpEndpoint: 'http://collector.new.internal:4318',
  otlpHeaders: { Authorization: 'Basic ...' },
});

console.log(getRuntimeConfig().otlpEndpoint);
// → 'http://collector.new.internal:4318'
```

Guardrails:

- If OTel providers are already registered (i.e. `registerOtelProviders()`
  has run) and a provider-changing field differs — `serviceName`,
  `environment`, `version`, `otelEnabled`, `tracingEnabled`, `metricsEnabled`,
  any `otlp*Endpoint` / `otlp*Headers` — this call throws
  `ConfigurationError`. Provider swap requires a process restart to avoid
  losing buffered exports. For hot-reloadable fields only (sampling,
  backpressure, exporter resilience, schema strictness, SLO toggles,
  security limits, PII depth), use `updateRuntimeConfig()` or
  `reloadRuntimeFromEnv()` instead — they never touch provider wiring.

### AsyncLocalStorage initialisation (ESM gotcha)

Under Node.js the library uses `node:async_hooks.AsyncLocalStorage` to
isolate propagation context per async task. In CJS builds the store is
attached synchronously at module load. Under pure ESM (`.mjs` entrypoints,
`tsx --import`) `require` is undefined, so the library falls back to a
fire-and-forget `await import('node:async_hooks')` that resolves on the
next microtask. Callers that bind propagation context inside top-level
async code before that microtask runs would hit the module-level fallback
store and leak context between concurrent requests.

For code paths that need a hard guarantee (typically: servers that start
accepting requests at module scope) prefer the async variant:

```typescript
import { setupTelemetryAsync } from '@provide-io/telemetry';

// Awaits ALS init before resolving. Throws ConfigurationError when
// AsyncLocalStorage is genuinely unavailable on a Node runtime.
await setupTelemetryAsync({ serviceName: 'my-app' });

// Safe to accept concurrent requests here.
```

The synchronous `setupTelemetry()` is preserved for backwards compatibility
and remains the right choice for non-async-init environments (bundled CJS
tests, vitest, scripts that do not race with request serving). It applies
a best-effort ALS check: when the init has not yet settled it schedules a
deferred check that records a `setupError` and logs a warning if ALS really
is unavailable — it does not throw in that case.

If you would rather compose the primitives yourself, both helpers remain
exported:

```typescript
import {
  setupTelemetry,
  awaitPropagationInit,
  isFallbackMode,
} from '@provide-io/telemetry';

setupTelemetry({ serviceName: 'my-app' });
await awaitPropagationInit();
if (isFallbackMode()) {
  throw new Error('AsyncLocalStorage unavailable — refusing to serve requests');
}
```

`awaitPropagationInit()` always resolves (it never rejects); inspect
`isFallbackMode()` / `isPropagationInitDone()` afterwards to branch on the
outcome.

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

<!-- BEGIN GENERATED CONFIG: typescript_summary -->
| Env var | Default | Description |
|---------|---------|-------------|
| `PROVIDE_TELEMETRY_SERVICE_NAME` | `provide-service` | Service identity attached to all signals |
| `PROVIDE_TELEMETRY_ENV` | `dev` | Deployment environment tag (e.g. dev, staging, prod) |
| `PROVIDE_TELEMETRY_VERSION` | `0.0.0` | Application version tag |
| `PROVIDE_TELEMETRY_STRICT_SCHEMA` | `false` | Master switch: when true, overrides event name strictness to on |
| `PROVIDE_LOG_LEVEL` | `INFO` | Log level: TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `PROVIDE_LOG_FORMAT` | `console` | Renderer: console, json, or pretty |
| `PROVIDE_LOG_INCLUDE_TIMESTAMP` | `true` | Add ISO-8601 timestamp to each log event |
| `PROVIDE_LOG_INCLUDE_CALLER` | `true` | Add filename and line number to each log event |
| `PROVIDE_LOG_SANITIZE` | `true` | Enable PII/sensitive field redaction in log output |
| `PROVIDE_LOG_PII_MAX_DEPTH` | `8` | Maximum nesting depth for PII/sensitive field traversal during sanitization |
| `PROVIDE_LOG_CODE_ATTRIBUTES` | `false` | Attach code attributes to OTel log records |
| `PROVIDE_LOG_PRETTY_KEY_COLOR` | `dim` | ANSI color name for keys in pretty format (see named colors below) |
| `PROVIDE_LOG_PRETTY_VALUE_COLOR` | `""` | ANSI color name for values in pretty format (empty = default) |
| `PROVIDE_LOG_PRETTY_FIELDS` | `""` | Comma-separated field names to display in pretty format |
| `PROVIDE_LOG_MODULE_LEVELS` | `""` | Per-module log level overrides (e.g. provide.server=DEBUG,asyncio=WARNING) |
| `PROVIDE_TRACE_ENABLED` | `true` | Enable the tracing signal and trace-provider setup (logs remain enabled) |
| `PROVIDE_TRACE_SAMPLE_RATE` | `1.0` | Trace sampling rate (0.0-1.0) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | — | Shared OTLP endpoint (fallback for all signals) |
| `OTEL_EXPORTER_OTLP_HEADERS` | — | Shared OTLP headers (fallback for all signals) |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | — | Per-signal OTLP endpoint for logs |
| `OTEL_EXPORTER_OTLP_LOGS_HEADERS` | — | Per-signal OTLP headers for logs |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | — | Per-signal OTLP endpoint for traces |
| `OTEL_EXPORTER_OTLP_TRACES_HEADERS` | — | Per-signal OTLP headers for traces |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | — | Per-signal OTLP endpoint for metrics |
| `OTEL_EXPORTER_OTLP_METRICS_HEADERS` | — | Per-signal OTLP headers for metrics |
<!-- END GENERATED CONFIG: typescript_summary -->

### Pretty renderer

Set `logFormat: 'pretty'` (or `PROVIDE_LOG_FORMAT=pretty`) for human-readable colored output during local development. Color support respects `FORCE_COLOR` and `NO_COLOR` environment variables.

```typescript
setupTelemetry({ logFormat: 'pretty' });
```

## Requirements

- Node.js ≥ 18
- TypeScript ≥ 5 (built with TypeScript 6)

## License

Apache-2.0. See [LICENSE](../LICENSES/Apache-2.0.txt).
