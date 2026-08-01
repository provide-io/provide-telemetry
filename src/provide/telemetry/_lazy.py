# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Lazy-import registry backing the ``provide.telemetry`` public facade.

The ``__getattr__`` hook itself must stay in ``__init__.py`` — PEP 562 only
consults the package module object — but the symbol table and the resolution
logic live here so the package init reads as a declaration of the public API
rather than as code.

Symbols are declared module-first (``module -> names``) and inverted into the
``name -> module`` lookup at import time. The inversion rejects a name claimed
by two modules, so a symbol moving between modules fails loudly at import
instead of silently resolving to whichever registration happened to run last.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# Module path → the symbols the public facade re-exports from it. Every name
# must be unique across the whole table; see _build_registry.
MODULE_EXPORTS: dict[str, tuple[str, ...]] = {
    "provide.telemetry.asgi": (
        "TelemetryMiddleware",
        "bind_websocket_context",
        "clear_websocket_context",
    ),
    "provide.telemetry.backpressure": (
        "QueuePolicy",
        "get_queue_policy",
        "set_queue_policy",
    ),
    "provide.telemetry.cardinality": (
        "CardinalityLimit",
        "clear_cardinality_limits",
        "get_cardinality_limits",
        "guard_attributes",
        "register_cardinality_limit",
    ),
    "provide.telemetry.classification": (
        "ClassificationPolicy",
        "ClassificationRule",
        "DataClass",
        "classify_key",
        "get_classification_policy",
        "register_classification_rule",
        "register_classification_rules",
        "set_classification_policy",
    ),
    "provide.telemetry.consent": (
        "ConsentLevel",
        "get_consent_level",
        "set_consent_level",
        "should_allow",
    ),
    "provide.telemetry.health": (
        "HealthSnapshot",
        "get_health_snapshot",
    ),
    # get_meter is owned by provide.telemetry.runtime, the canonical facade.
    "provide.telemetry.metrics": (
        "counter",
        "gauge",
        "histogram",
    ),
    "provide.telemetry.pii": (
        "PIIRule",
        "get_pii_rules",
        "get_secret_patterns",
        "register_pii_rule",
        "register_secret_pattern",
        "replace_pii_rules",
    ),
    "provide.telemetry.propagation": (
        "bind_propagation_context",
        "extract_w3c_context",
        "inject_traceparent",
        "parse_baggage",
    ),
    "provide.telemetry.receipts": (
        "RedactionReceipt",
        "enable_receipts",
        "get_emitted_receipts_for_tests",
    ),
    "provide.telemetry.resilience": (
        "ExporterPolicy",
        "get_exporter_policy",
        "set_exporter_policy",
    ),
    "provide.telemetry.runtime": (
        "FlushResult",
        "ProviderMode",
        "ReconfigureResult",
        "RuntimeState",
        "RuntimeStatus",
        "SignalFlushResult",
        "TelemetryRuntime",
        "flush",
        "flush_result",
        "get_logger",
        "get_meter",
        "get_runtime_config",
        "get_runtime_status",
        "get_strict_schema",
        "get_tracer",
        "provider_immutable_error",
        "provider_mode",
        "reconfigure_result",
        "reconfigure_telemetry",
        "reload_runtime_from_env",
        "runtime_state",
        "runtime_status",
        "set_strict_schema",
        "shutdown",
        "signal_flush_result",
        "start",
        "telemetry_config",
        "telemetry_runtime",
        "update_runtime_config",
    ),
    "provide.telemetry.sampling": (
        "SamplingPolicy",
        "get_sampling_policy",
        "set_sampling_policy",
        "should_sample",
    ),
    "provide.telemetry.slo": (
        "classify_error",
        "record_red_metrics",
        "record_use_metrics",
    ),
}


def _build_registry(module_exports: Mapping[str, tuple[str, ...]]) -> dict[str, str]:
    """Invert ``module -> names`` into ``name -> module``.

    Raises:
        RuntimeError: if two modules claim the same exported name.
    """
    registry: dict[str, str] = {}
    for module, names in module_exports.items():
        for name in names:
            owner = registry.get(name)
            if owner is not None:
                raise RuntimeError(f"{name!r} is exported by both {owner!r} and {module!r}")
            registry[name] = module
    return registry


# Symbol name → the module that owns it.
LAZY_REGISTRY: dict[str, str] = _build_registry(MODULE_EXPORTS)


def resolve(package: str, name: str) -> object:
    """Resolve ``name`` as a registered symbol, else as a subpackage of ``package``.

    Raises:
        AttributeError: if ``name`` is neither a registered symbol nor an
            importable subpackage.
    """
    module = LAZY_REGISTRY.get(name)
    if module is not None:
        return getattr(importlib.import_module(module), name)
    try:
        return importlib.import_module(f"{package}.{name}")
    except ImportError:
        raise AttributeError(f"module {package!r} has no attribute {name!r}") from None
