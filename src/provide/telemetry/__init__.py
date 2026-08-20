# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Public API for provide.telemetry.

Core telemetry symbols are eagerly imported.
Governance modules are mandatory by contract.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

from provide.telemetry import _lazy

# ── Eager: core symbols needed by every consumer ────────────────────────────
from provide.telemetry._masking import redact_config
from provide.telemetry.config import RuntimeOverrides, TelemetryConfig
from provide.telemetry.exceptions import ConfigurationError, ProviderImmutableError, TelemetryError
from provide.telemetry.levels import LogSeverity, level_order, parse_level, try_parse_level
from provide.telemetry.logger import bind_context, clear_context, logger, unbind_context
from provide.telemetry.logger.context import bind_session_context, clear_session_context, get_session_id
from provide.telemetry.schema.events import Event, EventSchemaError, event, event_name
from provide.telemetry.setup import flush_telemetry, setup_telemetry, shutdown_telemetry
from provide.telemetry.tracing import (
    get_trace_context,
    record_exception,
    set_attrs,
    set_trace_context,
    span,
    trace,
    tracer,
)

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
        guard_attributes,
        register_cardinality_limit,
    )
    from provide.telemetry.classification import (
        ClassificationPolicy,
        ClassificationRule,
        DataClass,
        classify_key,
        get_classification_policy,
        register_classification_rule,
        register_classification_rules,
        set_classification_policy,
    )
    from provide.telemetry.consent import ConsentLevel, get_consent_level, set_consent_level, should_allow
    from provide.telemetry.health import HealthSnapshot, get_health_snapshot
    from provide.telemetry.metrics import counter, gauge, histogram
    from provide.telemetry.pii import (
        PIIRule,
        get_pii_rules,
        get_secret_patterns,
        register_pii_rule,
        register_secret_pattern,
        replace_pii_rules,
    )
    from provide.telemetry.propagation import (
        bind_propagation_context,
        extract_w3c_context,
        inject_traceparent,
        parse_baggage,
    )
    from provide.telemetry.receipts import RedactionReceipt, enable_receipts, get_emitted_receipts_for_tests
    from provide.telemetry.resilience import ExporterPolicy, get_exporter_policy, set_exporter_policy
    from provide.telemetry.runtime import (
        FlushResult,
        ProviderMode,
        ReconfigureResult,
        RuntimeState,
        RuntimeStatus,
        SignalFlushResult,
        TelemetryRuntime,
        flush,
        flush_result,
        get_logger,
        get_meter,
        get_runtime_config,
        get_runtime_status,
        get_strict_schema,
        get_tracer,
        provider_immutable_error,
        provider_mode,
        reconfigure_result,
        reconfigure_telemetry,
        reload_runtime_from_env,
        runtime_state,
        runtime_status,
        set_strict_schema,
        shutdown,
        signal_flush_result,
        start,
        telemetry_config,
        telemetry_runtime,
        update_runtime_config,
    )
    from provide.telemetry.sampling import SamplingPolicy, get_sampling_policy, set_sampling_policy, should_sample
    from provide.telemetry.slo import classify_error, record_red_metrics, record_use_metrics


def __getattr__(name: str) -> object:
    return _lazy.resolve(__name__, name)


__all__ = [
    "CardinalityLimit",
    "ClassificationPolicy",
    "ClassificationRule",
    "ConfigurationError",
    "ConsentLevel",
    "DataClass",
    "Event",
    "EventSchemaError",
    "ExporterPolicy",
    "FlushResult",
    "HealthSnapshot",
    "LogSeverity",
    "PIIRule",
    "ProviderImmutableError",
    "ProviderMode",
    "QueuePolicy",
    "ReconfigureResult",
    "RedactionReceipt",
    "RuntimeOverrides",
    "RuntimeState",
    "RuntimeStatus",
    "SamplingPolicy",
    "SignalFlushResult",
    "TelemetryConfig",
    "TelemetryError",
    "TelemetryMiddleware",
    "TelemetryRuntime",
    "__version__",
    "bind_context",
    "bind_propagation_context",
    "bind_session_context",
    "bind_websocket_context",
    "classify_error",
    "classify_key",
    "clear_cardinality_limits",
    "clear_context",
    "clear_session_context",
    "clear_websocket_context",
    "counter",
    "enable_receipts",
    "event",
    "event_name",
    "extract_w3c_context",
    "flush",
    "flush_result",
    "flush_telemetry",
    "gauge",
    "get_cardinality_limits",
    "get_classification_policy",
    "get_consent_level",
    "get_emitted_receipts_for_tests",
    "get_exporter_policy",
    "get_health_snapshot",
    "get_logger",
    "get_meter",
    "get_pii_rules",
    "get_queue_policy",
    "get_runtime_config",
    "get_runtime_status",
    "get_sampling_policy",
    "get_secret_patterns",
    "get_session_id",
    "get_strict_schema",
    "get_trace_context",
    "get_tracer",
    "guard_attributes",
    "histogram",
    "inject_traceparent",
    "level_order",
    "logger",
    "parse_baggage",
    "parse_level",
    "provider_immutable_error",
    "provider_mode",
    "reconfigure_result",
    "reconfigure_telemetry",
    "record_exception",
    "record_red_metrics",
    "record_use_metrics",
    "redact_config",
    "register_cardinality_limit",
    "register_classification_rule",
    "register_classification_rules",
    "register_pii_rule",
    "register_secret_pattern",
    "reload_runtime_from_env",
    "replace_pii_rules",
    "runtime_state",
    "runtime_status",
    "set_attrs",
    "set_classification_policy",
    "set_consent_level",
    "set_exporter_policy",
    "set_queue_policy",
    "set_sampling_policy",
    "set_strict_schema",
    "set_trace_context",
    "setup_telemetry",
    "should_allow",
    "should_sample",
    "shutdown",
    "shutdown_telemetry",
    "signal_flush_result",
    "span",
    "start",
    "telemetry_config",
    "telemetry_runtime",
    "trace",
    "tracer",
    "try_parse_level",
    "unbind_context",
    "update_runtime_config",
]
