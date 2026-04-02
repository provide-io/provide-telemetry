# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Verify that importing provide.telemetry does NOT eagerly load heavy modules."""

from __future__ import annotations

import importlib
import sys


def _fresh_import_modules() -> set[str]:
    """Import provide.telemetry in a subprocess-like clean state and return loaded module names."""
    import provide

    to_remove = [k for k in sys.modules if k.startswith("provide.telemetry")]
    saved = {k: sys.modules.pop(k) for k in to_remove}
    old_telemetry_attr = getattr(provide, "telemetry", None)
    try:
        before = set(sys.modules.keys())
        importlib.import_module("provide.telemetry")
        after = set(sys.modules.keys())
        return {m for m in (after - before) if m.startswith("provide.telemetry")}
    finally:
        # Remove any modules created during the fresh import
        for k in list(sys.modules):
            if k.startswith("provide.telemetry"):
                del sys.modules[k]
        # Restore the original modules and package attribute
        sys.modules.update(saved)
        if old_telemetry_attr is not None:
            provide.telemetry = old_telemetry_attr


LAZY_MODULES = frozenset(
    {
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
    }
)


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

    with pytest.raises((AttributeError, ImportError)):
        from provide.telemetry import no_such_symbol  # noqa: F401


def test_inline_imports_resolve_in_setup() -> None:
    """Verify that inline imports in setup.py resolve the expected symbols."""
    from provide.telemetry.metrics.provider import _refresh_otel_metrics, setup_metrics, shutdown_metrics
    from provide.telemetry.runtime import apply_runtime_config

    assert callable(apply_runtime_config)
    assert callable(setup_metrics)
    assert callable(shutdown_metrics)
    assert callable(_refresh_otel_metrics)


def test_inline_imports_resolve_in_core() -> None:
    """Verify that inline imports in core.py resolve run_with_resilience."""
    from provide.telemetry.resilience import run_with_resilience

    assert callable(run_with_resilience)


def test_inline_imports_resolve_in_provider() -> None:
    """Verify that inline imports in provider.py resolve run_with_resilience."""
    from provide.telemetry.resilience import run_with_resilience

    assert callable(run_with_resilience)
