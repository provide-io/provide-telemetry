# Slim Core: Lazy Loading for FaaS

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `import provide.telemetry` from 34 eagerly-loaded modules to ~8 for the core path (logger + trace + config), with all other modules loaded lazily on first access. TypeScript gets the same benefit via ESM tree-shaking (already mostly works, just needs SLO to stop being eagerly imported).

**Architecture:** Python `__init__.py` becomes a thin facade that eagerly imports only the core symbols (setup, logger, trace, config, exceptions) and uses `__getattr__` for everything else. All existing imports continue to work — `from provide.telemetry import register_pii_rule` still works, it just doesn't load `pii.py` until that line runs. TypeScript `index.ts` already tree-shakes via ESM; the only change is confirming `sideEffects: false` in `package.json`.

**Tech Stack:** Python `__getattr__` (PEP 562), TypeScript ESM tree-shaking, no new dependencies.

---

## Task 1: Python — Rewrite `__init__.py` as lazy facade

**Files:**
- Modify: `src/provide/telemetry/__init__.py`

The end state: only `setup_telemetry`, `shutdown_telemetry`, `get_logger`, `logger`, `bind_context`, `unbind_context`, `clear_context`, `trace`, `tracer`, `get_tracer`, `get_trace_context`, `set_trace_context`, `TelemetryError`, `ConfigurationError`, `EventSchemaError`, `event_name`, `__version__` are eagerly imported. Everything else is lazy.

- [ ] **Step 1: Write the test that verifies lazy loading**

Create `tests/test_lazy_import.py`:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0

"""Verify that importing provide.telemetry does NOT eagerly load heavy modules."""

from __future__ import annotations

import sys
import importlib


def _fresh_import_modules() -> set[str]:
    """Import provide.telemetry in a subprocess-like clean state and return loaded module names."""
    # Remove all provide.telemetry modules from sys.modules to simulate fresh import.
    to_remove = [k for k in sys.modules if k.startswith("provide.telemetry")]
    saved = {k: sys.modules.pop(k) for k in to_remove}
    try:
        before = set(sys.modules.keys())
        importlib.import_module("provide.telemetry")
        after = set(sys.modules.keys())
        return {m for m in (after - before) if m.startswith("provide.telemetry")}
    finally:
        # Restore original modules so other tests are unaffected.
        for k, v in saved.items():
            sys.modules[k] = v


# Modules that MUST NOT be loaded on bare import.
LAZY_MODULES = frozenset({
    "provide.telemetry.asgi",
    "provide.telemetry.asgi.middleware",
    "provide.telemetry.asgi.websocket",
    "provide.telemetry.backpressure",
    "provide.telemetry.cardinality",
    "provide.telemetry.health",
    "provide.telemetry.headers",
    "provide.telemetry.metrics",
    "provide.telemetry.metrics.api",
    "provide.telemetry.metrics.fallback",
    "provide.telemetry.metrics.instruments",
    "provide.telemetry.metrics.provider",
    "provide.telemetry.pii",
    "provide.telemetry.propagation",
    "provide.telemetry.resilience",
    "provide.telemetry.runtime",
    "provide.telemetry.sampling",
    "provide.telemetry.slo",
})


def test_bare_import_does_not_load_heavy_modules() -> None:
    loaded = _fresh_import_modules()
    unexpected = loaded & LAZY_MODULES
    assert not unexpected, f"Eagerly loaded modules that should be lazy: {sorted(unexpected)}"


def test_bare_import_loads_core_modules() -> None:
    loaded = _fresh_import_modules()
    core = {
        "provide.telemetry",
        "provide.telemetry.config",
        "provide.telemetry.exceptions",
        "provide.telemetry.logger",
        "provide.telemetry.logger.context",
        "provide.telemetry.logger.core",
        "provide.telemetry.setup",
        "provide.telemetry.tracing",
        "provide.telemetry.schema",
        "provide.telemetry.schema.events",
    }
    missing = core - loaded
    assert not missing, f"Core modules not loaded on import: {sorted(missing)}"


def test_lazy_access_loads_module() -> None:
    """Accessing a lazy symbol must work and load the backing module."""
    from provide.telemetry import register_pii_rule  # noqa: F401

    assert "provide.telemetry.pii" in sys.modules


def test_lazy_access_slo() -> None:
    from provide.telemetry import record_red_metrics  # noqa: F401

    assert "provide.telemetry.slo" in sys.modules


def test_lazy_access_health() -> None:
    from provide.telemetry import get_health_snapshot  # noqa: F401

    assert "provide.telemetry.health" in sys.modules


def test_lazy_access_nonexistent_raises_attribute_error() -> None:
    import pytest

    with pytest.raises(AttributeError, match="no_such_symbol"):
        from provide.telemetry import no_such_symbol  # type: ignore[attr-defined]  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_lazy_import.py -v --no-cov`
Expected: `test_bare_import_does_not_load_heavy_modules` FAIL (18 unexpected modules loaded eagerly)

- [ ] **Step 3: Rewrite `__init__.py` as lazy facade**

Replace the entire content of `src/provide/telemetry/__init__.py` with:

```python
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Public API for provide.telemetry.

Core symbols (logger, tracing, config, exceptions, schema) are eagerly imported.
All other symbols are loaded lazily on first access via __getattr__ (PEP 562),
keeping the import footprint small for FaaS / serverless environments.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

# ── Eager: core symbols needed by every consumer ────────────────────────────

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.exceptions import ConfigurationError, TelemetryError
from provide.telemetry.logger import bind_context, clear_context, get_logger, logger, unbind_context
from provide.telemetry.logger.context import bind_session_context, clear_session_context, get_session_id
from provide.telemetry.schema.events import EventSchemaError, event_name
from provide.telemetry.setup import setup_telemetry, shutdown_telemetry
from provide.telemetry.tracing import get_trace_context, get_tracer, set_trace_context, trace, tracer

try:
    __version__ = version("provide-telemetry")
except (PackageNotFoundError, TypeError):
    __version__ = "0.0.0"

# ── Lazy: loaded on first access ────────────────────────────────────────────

if TYPE_CHECKING:
    from provide.telemetry.asgi import TelemetryMiddleware, bind_websocket_context, clear_websocket_context
    from provide.telemetry.backpressure import QueuePolicy, get_queue_policy, set_queue_policy
    from provide.telemetry.cardinality import (
        CardinalityLimit,
        clear_cardinality_limits,
        get_cardinality_limits,
        register_cardinality_limit,
    )
    from provide.telemetry.health import HealthSnapshot, get_health_snapshot
    from provide.telemetry.metrics import counter, gauge, get_meter, histogram
    from provide.telemetry.pii import PIIRule, get_pii_rules, register_pii_rule, replace_pii_rules
    from provide.telemetry.propagation import bind_propagation_context, extract_w3c_context
    from provide.telemetry.resilience import ExporterPolicy, get_exporter_policy, set_exporter_policy
    from provide.telemetry.runtime import (
        get_runtime_config,
        reconfigure_telemetry,
        reload_runtime_from_env,
        update_runtime_config,
    )
    from provide.telemetry.sampling import SamplingPolicy, get_sampling_policy, set_sampling_policy, should_sample
    from provide.telemetry.slo import classify_error, record_red_metrics, record_use_metrics

# Maps symbol name → (module_path, attribute_name).
_LAZY_REGISTRY: dict[str, tuple[str, str]] = {}


def _register(module: str, *names: str) -> None:
    for name in names:
        _LAZY_REGISTRY[name] = (module, name)


_register("provide.telemetry.asgi", "TelemetryMiddleware", "bind_websocket_context", "clear_websocket_context")
_register("provide.telemetry.backpressure", "QueuePolicy", "get_queue_policy", "set_queue_policy")
_register(
    "provide.telemetry.cardinality",
    "CardinalityLimit", "clear_cardinality_limits", "get_cardinality_limits", "register_cardinality_limit",
)
_register("provide.telemetry.health", "HealthSnapshot", "get_health_snapshot")
_register("provide.telemetry.metrics", "counter", "gauge", "get_meter", "histogram")
_register("provide.telemetry.pii", "PIIRule", "get_pii_rules", "register_pii_rule", "replace_pii_rules")
_register("provide.telemetry.propagation", "bind_propagation_context", "extract_w3c_context")
_register("provide.telemetry.resilience", "ExporterPolicy", "get_exporter_policy", "set_exporter_policy")
_register(
    "provide.telemetry.runtime",
    "get_runtime_config", "reconfigure_telemetry", "reload_runtime_from_env", "update_runtime_config",
)
_register("provide.telemetry.sampling", "SamplingPolicy", "get_sampling_policy", "set_sampling_policy", "should_sample")
_register("provide.telemetry.slo", "classify_error", "record_red_metrics", "record_use_metrics")


def __getattr__(name: str) -> object:
    entry = _LAZY_REGISTRY.get(name)
    if entry is not None:
        module_path, attr_name = entry
        import importlib

        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Eager (core)
    "ConfigurationError",
    "EventSchemaError",
    "TelemetryConfig",
    "TelemetryError",
    "__version__",
    "bind_context",
    "bind_session_context",
    "clear_context",
    "clear_session_context",
    "event_name",
    "get_logger",
    "get_session_id",
    "get_trace_context",
    "get_tracer",
    "logger",
    "set_trace_context",
    "setup_telemetry",
    "shutdown_telemetry",
    "trace",
    "tracer",
    "unbind_context",
    # Lazy (loaded on first access)
    "CardinalityLimit",
    "ExporterPolicy",
    "HealthSnapshot",
    "PIIRule",
    "QueuePolicy",
    "SamplingPolicy",
    "TelemetryMiddleware",
    "bind_propagation_context",
    "bind_websocket_context",
    "classify_error",
    "clear_cardinality_limits",
    "clear_websocket_context",
    "counter",
    "extract_w3c_context",
    "gauge",
    "get_cardinality_limits",
    "get_exporter_policy",
    "get_health_snapshot",
    "get_meter",
    "get_pii_rules",
    "get_queue_policy",
    "get_runtime_config",
    "get_sampling_policy",
    "histogram",
    "reconfigure_telemetry",
    "record_red_metrics",
    "record_use_metrics",
    "register_cardinality_limit",
    "register_pii_rule",
    "reload_runtime_from_env",
    "replace_pii_rules",
    "set_exporter_policy",
    "set_queue_policy",
    "set_sampling_policy",
    "should_sample",
    "update_runtime_config",
]
```

- [ ] **Step 4: Run lazy import tests**

Run: `uv run python -m pytest tests/test_lazy_import.py -v --no-cov`
Expected: All 6 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run python scripts/run_pytest_gate.py`
Expected: 100% coverage, all tests pass (1298+)

- [ ] **Step 6: Verify module count dropped**

Run:
```bash
python3 -c "
import sys
before = set(sys.modules.keys())
import provide.telemetry
after = set(sys.modules.keys())
loaded = sorted(m for m in (after - before) if m.startswith('provide.telemetry'))
print(f'Modules loaded: {len(loaded)}')
for m in loaded: print(f'  {m}')
"
```
Expected: ~10-12 modules (down from 34)

- [ ] **Step 7: Run mutation gate**

Run: `uv run python scripts/run_mutation_gate.py --python-version 3.11 --retries 1 --min-mutation-score 100`
Expected: 0 surviving mutants

- [ ] **Step 8: Commit**

```bash
git add src/provide/telemetry/__init__.py tests/test_lazy_import.py
git commit -m "perf: lazy-load heavy modules in __init__.py for FaaS cold start

Core symbols (logger, trace, config, exceptions, schema) loaded eagerly.
All other modules (pii, resilience, metrics, slo, asgi, health, etc.) loaded
on first access via __getattr__ (PEP 562).

Reduces import from 34 modules to ~10 for consumers who only need logging + tracing."
```

---

## Task 2: TypeScript — Confirm tree-shaking and add `sideEffects`

**Files:**
- Modify: `typescript/package.json`
- Create: `typescript/tests/treeshake.test.ts`

- [ ] **Step 1: Write the test that verifies sideEffects is set**

Create `typescript/tests/treeshake.test.ts`:

```typescript
// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import pkg from '../package.json';

describe('tree-shaking support', () => {
  it('package.json has sideEffects: false', () => {
    expect(pkg['sideEffects']).toBe(false);
  });

  it('package.json has module field pointing to ESM entry', () => {
    expect(pkg['type']).toBe('module');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd typescript && npm test -- tests/treeshake.test.ts`
Expected: `sideEffects` test FAIL (field not present yet)

- [ ] **Step 3: Add `sideEffects: false` to `package.json`**

In `typescript/package.json`, add at the top level (after `"type": "module"`):

```json
"sideEffects": false,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd typescript && npm test -- tests/treeshake.test.ts`
Expected: PASS

- [ ] **Step 5: Run full TypeScript test suite with coverage**

Run: `cd typescript && npm test -- --coverage`
Expected: 804+ tests pass, 100% coverage

- [ ] **Step 6: Commit**

```bash
git add typescript/package.json typescript/tests/treeshake.test.ts
git commit -m "perf(ts): add sideEffects: false for tree-shaking in FaaS bundlers"
```

---

## Task 3: Verify E2E — both languages still work with lazy loading

**Files:** None modified — verification only.

- [ ] **Step 1: Run Python OpenObserve examples**

```bash
OPENOBSERVE_URL=http://localhost:5080/api/default \
OPENOBSERVE_USER=admin@provide.test \
OPENOBSERVE_PASSWORD=Complexpass#123 \
uv run --group dev --extra otel python examples/openobserve/02_verify_ingestion.py
```
Expected: `verification passed`

- [ ] **Step 2: Run TypeScript OpenObserve examples**

```bash
cd typescript
OPENOBSERVE_URL=http://localhost:5080/api/default \
OPENOBSERVE_USER=admin@provide.test \
OPENOBSERVE_PASSWORD=Complexpass#123 \
OPENOBSERVE_REQUIRED_SIGNALS=logs,traces,metrics \
npx tsx examples/openobserve/02_verify_ingestion.ts
```
Expected: `verification passed`

- [ ] **Step 3: Run spec conformance**

```bash
uv run python spec/validate_conformance.py
```
Expected: `PASSED — all languages conform to spec.`

- [ ] **Step 4: Final commit with E2E proof**

No code changes — just verification that lazy loading didn't break anything.
