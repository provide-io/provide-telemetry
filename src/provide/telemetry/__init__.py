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


def _register(module: str, *names: str) -> None:  # pragma: no mutate
    for name in names:
        _LAZY_REGISTRY[name] = (module, name)  # pragma: no mutate


_register("provide.telemetry.asgi", "TelemetryMiddleware", "bind_websocket_context", "clear_websocket_context")
_register("provide.telemetry.backpressure", "QueuePolicy", "get_queue_policy", "set_queue_policy")
_register(
    "provide.telemetry.cardinality",
    "CardinalityLimit",
    "clear_cardinality_limits",
    "get_cardinality_limits",
    "register_cardinality_limit",
)
_register("provide.telemetry.health", "HealthSnapshot", "get_health_snapshot")
_register("provide.telemetry.metrics", "counter", "gauge", "get_meter", "histogram")
_register("provide.telemetry.pii", "PIIRule", "get_pii_rules", "register_pii_rule", "replace_pii_rules")
_register("provide.telemetry.propagation", "bind_propagation_context", "extract_w3c_context")
_register("provide.telemetry.resilience", "ExporterPolicy", "get_exporter_policy", "set_exporter_policy")
_register(
    "provide.telemetry.runtime",
    "get_runtime_config",
    "reconfigure_telemetry",
    "reload_runtime_from_env",
    "update_runtime_config",
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
    # Support subpackage access (e.g., provide.telemetry.asgi)
    import importlib

    try:
        return importlib.import_module(f"{__name__}.{name}")
    except ImportError:
        pass
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CardinalityLimit",
    "ConfigurationError",
    "EventSchemaError",
    "ExporterPolicy",
    "HealthSnapshot",
    "PIIRule",
    "QueuePolicy",
    "SamplingPolicy",
    "TelemetryConfig",
    "TelemetryError",
    "TelemetryMiddleware",
    "__version__",
    "bind_context",
    "bind_propagation_context",
    "bind_session_context",
    "bind_websocket_context",
    "classify_error",
    "clear_cardinality_limits",
    "clear_context",
    "clear_session_context",
    "clear_websocket_context",
    "counter",
    "event_name",
    "extract_w3c_context",
    "gauge",
    "get_cardinality_limits",
    "get_exporter_policy",
    "get_health_snapshot",
    "get_logger",
    "get_meter",
    "get_pii_rules",
    "get_queue_policy",
    "get_runtime_config",
    "get_sampling_policy",
    "get_session_id",
    "get_trace_context",
    "get_tracer",
    "histogram",
    "logger",
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
    "set_trace_context",
    "setup_telemetry",
    "should_sample",
    "shutdown_telemetry",
    "trace",
    "tracer",
    "unbind_context",
    "update_runtime_config",
]
