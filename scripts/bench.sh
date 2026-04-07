#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
#
# Cross-language benchmark runner.
# Usage:
#   ./scripts/bench.sh            # all three languages
#   ./scripts/bench.sh python      # Python only
#   ./scripts/bench.sh typescript   # TypeScript only
#   ./scripts/bench.sh go           # Go only

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

LANG_FILTER="${1:-all}"
SEP="────────────────────────────────────────────────────────────────"

# ── Python ───────────────────────────────────────────────────────────────────
run_python() {
  echo "🐍 Python"
  echo "$SEP"
  uv run python -c "
import os, time
from provide.telemetry import setup_telemetry, shutdown_telemetry, event_name, get_logger
from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy, should_sample, reset_sampling_for_tests
from provide.telemetry.schema.events import validate_event_name
from provide.telemetry.logger.processors import sanitize_sensitive_fields
from provide.telemetry.pii import reset_pii_rules_for_tests
from provide.telemetry.backpressure import QueuePolicy, set_queue_policy, try_acquire, release, reset_queues_for_tests
from provide.telemetry.health import get_health_snapshot, reset_health_for_tests
from provide.telemetry.metrics.fallback import Counter, Gauge, Histogram

# Initialize telemetry only when OTel endpoint is configured.
# Without OTel, we measure raw function throughput (no provider overhead).
import os
os.environ['PROVIDE_LOG_LEVEL'] = 'ERROR'  # suppress log noise during benchmarks
if os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT'):
    setup_telemetry()
log = get_logger('bench')

N = 50_000

reset_sampling_for_tests()
reset_queues_for_tests()
reset_health_for_tests()
reset_pii_rules_for_tests()

def bench(name, fn, iterations=N):
    for _ in range(1000): fn()  # warmup
    start = time.perf_counter_ns()
    for _ in range(iterations): fn()
    ns = (time.perf_counter_ns() - start) / iterations
    print(f'  {name:<32} {ns:>10.0f} ns/op')

bench('eventName(3-seg)', lambda: event_name('auth', 'login', 'success'))
bench('eventName(5-seg)', lambda: event_name('payment', 'subscription', 'renewal', 'charge', 'success'))

set_sampling_policy('logs', SamplingPolicy(default_rate=1.0))
bench('shouldSample(rate=1)', lambda: should_sample('logs'))
set_sampling_policy('logs', SamplingPolicy(default_rate=0.0))
bench('shouldSample(rate=0)', lambda: should_sample('logs'))
set_sampling_policy('logs', SamplingPolicy(default_rate=0.5, overrides={'auth.login': 1.0}))
bench('shouldSample(override)', lambda: should_sample('logs', key='auth.login'))

proc = sanitize_sensitive_fields(enabled=True)
small = {'password': 'secret', 'token': 'abc', 'request_id': 'r1'}  # pragma: allowlist secret
bench('sanitize(small)', lambda: proc(None, 'info', small))
large = {f'field_{i}': f'value_{i}' for i in range(50)}
large['password'] = 'secret'  # pragma: allowlist secret
bench('sanitize(large/50)', lambda: proc(None, 'info', large), iterations=10_000)
proc_off = sanitize_sensitive_fields(enabled=False)
bench('sanitize(disabled)', lambda: proc_off(None, 'info', small))

set_queue_policy(QueuePolicy())
bench('tryAcquire+release', lambda: release(try_acquire('logs')))

bench('getHealthSnapshot', lambda: get_health_snapshot(), iterations=10_000)

ctr = Counter('bench.counter')
bench('counter.add', lambda: ctr.add(1))
g = Gauge('bench.gauge')
bench('gauge.set', lambda: g.set(42.0))
h = Histogram('bench.histogram')
bench('histogram.record', lambda: h.record(3.14))

log.info('bench.python.complete', extra={'language': 'python'})
shutdown_telemetry()
"
  echo ""
}

# ── TypeScript ───────────────────────────────────────────────────────────────
run_typescript() {
  echo "🟦 TypeScript"
  echo "$SEP"
  cd typescript
  npx tsx -e "
import { performance } from 'node:perf_hooks';
import { setSamplingPolicy, shouldSample, _resetSamplingForTests } from './src/sampling.ts';
import { eventName } from './src/schema.ts';
import { sanitize, resetPiiRulesForTests } from './src/pii.ts';
import { tryAcquire, release, setQueuePolicy, _resetBackpressureForTests } from './src/backpressure.ts';
import { getHealthSnapshot, _resetHealthForTests } from './src/health.ts';
import { counter, gauge, histogram } from './src/metrics.ts';
import { setupTelemetry, _resetConfig } from './src/config.ts';
import { shutdownTelemetry } from './src/shutdown.ts';
import { getLogger, _resetRootLogger } from './src/logger.ts';

_resetConfig();
_resetRootLogger();
_resetSamplingForTests();
_resetBackpressureForTests();
_resetHealthForTests();
resetPiiRulesForTests();
setupTelemetry({ serviceName: 'bench-ts', logLevel: 'silent' });

const N = 50_000;

function bench(name: string, fn: () => void, iterations = N): void {
  for (let i = 0; i < 1000; i++) fn();
  const start = performance.now();
  for (let i = 0; i < iterations; i++) fn();
  const ns = ((performance.now() - start) * 1_000_000) / iterations;
  console.log('  ' + name.padEnd(32) + ns.toFixed(0).padStart(10) + ' ns/op');
}

bench('eventName(3-seg)', () => eventName('auth', 'login', 'success'));
bench('eventName(5-seg)', () => eventName('payment', 'subscription', 'renewal', 'charge', 'success'));

setSamplingPolicy('logs', { defaultRate: 1.0 });
bench('shouldSample(rate=1)', () => shouldSample('logs'));
setSamplingPolicy('logs', { defaultRate: 0.0 });
bench('shouldSample(rate=0)', () => shouldSample('logs'));
setSamplingPolicy('logs', { defaultRate: 0.5, overrides: { 'auth.login': 1.0 } });
bench('shouldSample(override)', () => shouldSample('logs', 'auth.login'));

bench('sanitize(small)', () => {
  sanitize({ password: 'secret', token: 'abc', request_id: 'r1' }); // pragma: allowlist secret
});
bench('sanitize(large/50)', () => {
  const p: Record<string, unknown> = {};
  for (let i = 0; i < 50; i++) p['field_' + i] = 'value_' + i;
  p['password'] = 'secret'; // pragma: allowlist secret
  sanitize(p);
}, 10_000);

setQueuePolicy({ maxLogs: 0, maxTraces: 0, maxMetrics: 0 });
bench('tryAcquire+release', () => { const t = tryAcquire('logs'); if (t) release(t); });

bench('getHealthSnapshot', () => getHealthSnapshot(), 10_000);

const c = counter('bench_counter');
bench('counter.add', () => c.add(1));
const g = gauge('bench_gauge');
bench('gauge.set', () => g.set(42.0));
const h = histogram('bench_histogram');
bench('histogram.record', () => h.record(3.14));

const log = getLogger('bench');
log.info({ event: 'bench.typescript.complete', language: 'typescript' });
shutdownTelemetry().catch(() => {});
"
  cd ..
  echo ""
}

# ── Go ───────────────────────────────────────────────────────────────────────
run_go() {
  echo "🐹 Go"
  echo "$SEP"
  cd go
  go test -run='^$' -bench=. -benchmem -count=1 ./... 2>&1 \
    | grep '^Benchmark' \
    | awk '{
        name = $1
        sub(/-[0-9]+$/, "", name)
        sub(/^Benchmark/, "", name)
        # Map Go PascalCase names to shared camelCase names
        if (name == "EventName_3Segments")          name = "eventName(3-seg)"
        else if (name == "EventName_5Segments")     name = "eventName(5-seg)"
        else if (name == "ShouldSample_RateOne")    name = "shouldSample(rate=1)"
        else if (name == "ShouldSample_RateZero")   name = "shouldSample(rate=0)"
        else if (name == "ShouldSample_WithOverride") name = "shouldSample(override)"
        else if (name == "SanitizePayload_SmallFlat") name = "sanitize(small)"
        else if (name == "SanitizePayload_LargeFlat") name = "sanitize(large/50)"
        else if (name == "SanitizePayload_Disabled")  name = "sanitize(disabled)"
        else if (name == "TryAcquireRelease_Unlimited") name = "tryAcquire+release"
        else if (name == "GetHealthSnapshot")       name = "getHealthSnapshot"
        else if (name == "Counter_Add")             name = "counter.add"
        else if (name == "Gauge_Set")               name = "gauge.set"
        else if (name == "Histogram_Record")        name = "histogram.record"
        # Extract ns/op field (field after iteration count)
        for (i = 3; i <= NF; i++) {
          if ($(i) == "ns/op") { nsop = $(i-1); break }
        }
        printf "  %-32s %10s ns/op\n", name, nsop
      }'
  cd ..
  echo ""
}

# ── Dispatch ─────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo " provide-telemetry benchmarks"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

case "$LANG_FILTER" in
  python|py)      run_python ;;
  typescript|ts)  run_typescript ;;
  go)             run_go ;;
  all)            run_python; run_typescript; run_go ;;
  *)              echo "Usage: $0 [python|typescript|go|all]"; exit 1 ;;
esac
