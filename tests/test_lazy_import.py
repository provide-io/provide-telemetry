# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Verify that importing provide.telemetry does NOT eagerly load heavy modules."""

from __future__ import annotations

import json
import subprocess  # nosec
import sys
import textwrap


def _fresh_import_modules() -> set[str]:
    """Import provide.telemetry in a real clean subprocess and return loaded module names."""
    script = textwrap.dedent(
        """
        import importlib
        import json
        import sys

        before = set(sys.modules)
        importlib.import_module("provide.telemetry")
        after = set(sys.modules)
        loaded = sorted(m for m in (after - before) if m.startswith("provide.telemetry"))
        print(json.dumps(loaded))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=True,
        text=True,
    )
    return set(json.loads(proc.stdout))


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
    from provide.telemetry import register_pii_rule

    assert "provide.telemetry.pii" in sys.modules
    assert callable(register_pii_rule)


def test_lazy_access_slo() -> None:
    from provide.telemetry import record_red_metrics

    assert "provide.telemetry.slo" in sys.modules
    assert callable(record_red_metrics)


def test_lazy_access_health() -> None:
    from provide.telemetry import get_health_snapshot

    assert "provide.telemetry.health" in sys.modules
    assert callable(get_health_snapshot)


def test_lazy_registry_maps_to_correct_modules() -> None:
    """Verify LAZY_REGISTRY entries name the module that owns each symbol."""
    from provide.telemetry._lazy import LAZY_REGISTRY

    # Spot-check several entries across different modules.
    assert LAZY_REGISTRY["counter"] == "provide.telemetry.metrics"
    assert LAZY_REGISTRY["register_pii_rule"] == "provide.telemetry.pii"
    assert LAZY_REGISTRY["get_health_snapshot"] == "provide.telemetry.health"
    assert LAZY_REGISTRY["TelemetryMiddleware"] == "provide.telemetry.asgi"
    assert LAZY_REGISTRY["should_sample"] == "provide.telemetry.sampling"


def test_lazy_registry_owns_every_declared_export() -> None:
    """Every name in MODULE_EXPORTS is reachable and maps back to its module."""
    from provide.telemetry._lazy import LAZY_REGISTRY, MODULE_EXPORTS

    declared = {name: module for module, names in MODULE_EXPORTS.items() for name in names}
    assert declared == LAZY_REGISTRY


def test_lazy_registry_rejects_duplicate_owners() -> None:
    """A symbol claimed by two modules fails loudly instead of silently shadowing."""
    import pytest

    from provide.telemetry._lazy import _build_registry

    with pytest.raises(RuntimeError, match="exported by both"):
        _build_registry({"mod.a": ("dupe",), "mod.b": ("dupe",)})


def test_lazy_registry_has_no_duplicate_declarations() -> None:
    """The shipped table must not declare the same name under two modules."""
    from provide.telemetry._lazy import MODULE_EXPORTS, _build_registry

    assert _build_registry(MODULE_EXPORTS)  # raises RuntimeError on a duplicate


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
