# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Structlog processors."""

from __future__ import annotations

import hashlib
import logging
import re
import sys
import traceback
import types
from typing import Any

import structlog

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger.context import get_context
from provide.telemetry.schema.events import validate_event_name, validate_required_keys
from provide.telemetry.tracing.context import get_span_id, get_trace_id


def _get_active_config() -> Any | None:
    """Return the active runtime config without eagerly loading the runtime module."""
    runtime = sys.modules.get("provide.telemetry.runtime")
    if runtime is None:
        return None
    return getattr(runtime, "_active_config", None)  # pragma: no mutate — _active_config always exists as module var; 2-arg vs 3-arg equivalent


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Keys that must survive harden_input truncation regardless of insertion order.
# These are structlog/telemetry control fields; losing them silently corrupts
# routing, filtering, and trace correlation downstream.
_HARDEN_PRIORITY_KEYS: frozenset[str] = frozenset(
    {"event", "level", "timestamp", "trace_id", "span_id", "logger", "logger_name"}
)

TRACE_LEVEL = 5

# Fast lowercase level → numeric lookup (avoids normalize + getLevelName per message)
_FAST_LEVEL_LOOKUP: dict[str, int] = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": TRACE_LEVEL,
}


def inject_das_fields(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Extract DA(R)S fields from an :class:`Event` instance into the log record."""
    from provide.telemetry.schema.events import Event

    ev = event_dict.get("event")
    if isinstance(ev, Event):
        event_dict["domain"] = ev.domain
        event_dict["action"] = ev.action
        if ev.resource is not None:
            event_dict["resource"] = ev.resource
        event_dict["status"] = ev.status
        event_dict["event"] = str(ev)
    return event_dict


def merge_runtime_context(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict.update(get_context())
    trace_id = get_trace_id()
    span_id = get_span_id()
    if trace_id is not None:
        event_dict["trace_id"] = trace_id
    if span_id is not None:
        event_dict["span_id"] = span_id
    return event_dict


def inject_logger_name(logger: Any, _: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Ensure structured JSON output exposes the logger name canonically."""
    name = event_dict.get("logger_name") or event_dict.get("logger")
    if name is None:
        name = getattr(logger, "name", None)
    if name:
        event_dict["logger_name"] = str(name)
    return event_dict


def _compute_error_fingerprint(exc_type: str, tb: types.TracebackType | None) -> str:
    """Generate a stable 12-char hex fingerprint from exception type + top 3 frames."""
    parts = [exc_type.lower()]
    if tb is not None:
        for frame in traceback.extract_tb(tb)[-3:]:
            leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]  # pragma: no mutate
            basename = leaf.rsplit(".", 1)[0].lower()
            func = (frame.name or "").lower()
            parts.append(f"{basename}:{func}")
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:12]  # pragma: no mutate


def add_error_fingerprint(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Structlog processor: add stable error_fingerprint on error events."""
    exc_info = event_dict.get("exc_info")
    if exc_info is True:
        exc_info = sys.exc_info()
    if isinstance(exc_info, tuple) and len(exc_info) == 3 and exc_info[1] is not None:
        exc_type_name = type(exc_info[1]).__name__
        event_dict["error_fingerprint"] = _compute_error_fingerprint(exc_type_name, exc_info[2])
        return event_dict
    if isinstance(exc_info, BaseException):
        event_dict["error_fingerprint"] = _compute_error_fingerprint(type(exc_info).__name__, exc_info.__traceback__)
        return event_dict
    exc_name = event_dict.get("exc_name") or event_dict.get("exception")
    if exc_name:
        event_dict["error_fingerprint"] = _compute_error_fingerprint(str(exc_name), None)
    return event_dict


def harden_input(max_value_length: int, max_attr_count: int, max_depth: int) -> Any:
    """Structlog processor: truncate values, strip control chars, limit attributes."""

    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        live = _get_active_config()
        _max_value_length = live.security.max_attr_value_length if live is not None else max_value_length
        _max_attr_count = live.security.max_attr_count if live is not None else max_attr_count
        _max_depth = live.security.max_nesting_depth if live is not None else max_depth

        def _clean_value(value: object, depth: int) -> object:
            if isinstance(value, str):
                cleaned = _CONTROL_CHAR_RE.sub("", value)
                if len(cleaned) > _max_value_length:  # pragma: no mutate
                    return cleaned[:_max_value_length]
                return cleaned
            if isinstance(value, dict) and depth < _max_depth:
                return {k: _clean_value(v, depth + 1) for k, v in value.items()}
            if isinstance(value, list) and depth < _max_depth:
                return [_clean_value(item, depth + 1) for item in value]  # pragma: no mutate
            return value

        if _max_attr_count > 0 and len(event_dict) > _max_attr_count:  # pragma: no mutate
            # Preserve control/telemetry fields first, then fill with user payload.
            # Simple first-N truncation would silently drop level, trace_id, etc.
            # when callers pass many keyword arguments.
            priority = {k: event_dict[k] for k in _HARDEN_PRIORITY_KEYS if k in event_dict}
            remaining = max(0, _max_attr_count - len(priority))
            user_keys = [k for k in event_dict if k not in _HARDEN_PRIORITY_KEYS]
            event_dict = {**priority, **{k: event_dict[k] for k in user_keys[:remaining]}}
        return {k: _clean_value(v, 0) for k, v in event_dict.items()}

    return _processor


def add_standard_fields(config: TelemetryConfig) -> Any:
    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("service", config.service_name)
        event_dict.setdefault("env", config.environment)
        event_dict.setdefault("version", config.version)
        live = _get_active_config()
        include_error_taxonomy = (
            live.slo.include_error_taxonomy if live is not None else config.slo.include_error_taxonomy
        )
        if include_error_taxonomy and "error_type" not in event_dict and "exc_name" in event_dict:
            from provide.telemetry.slo import classify_error  # lazy: avoid loading metrics at logging config time

            status_code = event_dict.get("status_code")
            typed_status = status_code if isinstance(status_code, int) else None
            event_dict.update(classify_error(str(event_dict["exc_name"]), typed_status))
        return event_dict

    return _processor


_BACKPRESSURE_TICKET_KEY = "__provide_telemetry_backpressure_ticket__"


def apply_sampling(_: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    from provide.telemetry.backpressure import try_acquire
    from provide.telemetry.health import increment_emitted
    from provide.telemetry.sampling import should_sample

    try:
        from provide.telemetry.consent import should_allow
    except ImportError:  # pragma: no cover — governance module stripped

        def should_allow(signal: str, log_level: str | None = None) -> bool:  # noqa: ARG001
            return True

    if not should_allow("logs", method_name):
        raise structlog.DropEvent()
    event_name = str(event_dict.get("event", ""))  # pragma: no mutate
    if not should_sample("logs", event_name):
        raise structlog.DropEvent()
    ticket = try_acquire("logs")
    if ticket is None:
        raise structlog.DropEvent()  # backpressure full; dropped counter already incremented
    increment_emitted("logs")
    # Stash the ticket; release_backpressure_ticket (final processor, after the
    # renderer) drops it. This bounds queue depth across the actual emit work
    # — sanitization, caller capture, rendering — instead of releasing
    # immediately as the original code did.
    event_dict[_BACKPRESSURE_TICKET_KEY] = ticket
    return event_dict


def release_backpressure_ticket(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Release the backpressure ticket stashed by apply_sampling.

    Positioned just BEFORE the renderer in the chain — the renderer consumes
    event_dict and returns a string, after which the ticket would be
    unreachable. Releasing here bounds the ticket across sanitization,
    caller-capture, and any per-module level filtering.

    Cross-language contract — narrower than TS/Go/Rust:
        TypeScript, Go, and Rust hold the ticket through their entire emit
        path including handler I/O (try { emit } finally { release }).
        Python releases BEFORE the renderer because structlog's processor
        chain doesn't natively support try/finally semantics across the
        chain — wrapping the renderer or hooking the underlying logger
        emit would be invasive and structlog-version-coupled.

        Practical impact: Python's backpressure bounds the expensive
        in-process work (sanitization, caller capture, per-module level
        filtering) but does NOT bound JSON serialisation or handler I/O
        (file write, stderr write, OTLP HTTP POST). Slow sinks/handlers
        do not back-pressure on the producer in Python. If you have a
        slow handler and need true I/O backpressure, wrap your handler
        in an external bounded queue.

    The level filter is positioned BEFORE apply_sampling so its DropEvent
    path doesn't strand a ticket between acquire and this release.
    """
    from provide.telemetry.backpressure import release

    ticket = event_dict.pop(_BACKPRESSURE_TICKET_KEY, None)
    if ticket is not None:
        release(ticket)
    return event_dict


def enforce_event_schema(config: TelemetryConfig) -> Any:
    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        live = _get_active_config()
        live_strict = live.strict_schema if live is not None else config.strict_schema
        live_event_schema = live.event_schema if live is not None else config.event_schema
        strict_event_name = True if live_strict else live_event_schema.strict_event_name
        required_keys = live_event_schema.required_keys
        event = str(event_dict.get("event", ""))
        validate_event_name(event, strict_event_name=strict_event_name)
        validate_required_keys(event_dict, required_keys)
        return event_dict

    return _processor


def sanitize_sensitive_fields(enabled: bool, max_depth: int = 8) -> Any:  # pragma: no mutate
    from provide.telemetry.pii import sanitize_payload

    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        live = _get_active_config()
        _max_depth = live.pii_max_depth if live is not None else max_depth
        return sanitize_payload(event_dict, enabled, max_depth=_max_depth)

    return _processor


class _LevelFilter:
    """Per-module log level filter.

    FilteringBoundLogger handles the default level at zero cost.  This
    processor handles **module-level overrides** — e.g. ``asyncio=WARNING``
    while the default is ``INFO``.  It drops events whose level is below
    the threshold for their module (matched by longest-prefix).

    Placed late in the processor chain so enrichment processors run first.
    """

    __slots__ = ("_default_numeric", "_module_numerics", "_sorted_prefixes")

    def __init__(self, default_level: str, module_levels: dict[str, str]) -> None:
        self._default_numeric = _FAST_LEVEL_LOOKUP.get(default_level.lower(), logging.INFO)
        self._module_numerics: dict[str, int] = {
            module: _FAST_LEVEL_LOOKUP.get(lvl.lower(), logging.INFO) for module, lvl in module_levels.items()
        }
        # Longest prefix first for correct matching
        self._sorted_prefixes = sorted(self._module_numerics.keys(), key=lambda k: len(k), reverse=True)

    def __call__(self, _: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        logger_name: str = event_dict.get("logger_name", event_dict.get("logger", ""))
        event_level = _FAST_LEVEL_LOOKUP.get(event_dict.get("level", method_name).lower(), logging.INFO)

        threshold = self._default_numeric
        for prefix in self._sorted_prefixes:
            if prefix == "" or logger_name == prefix or logger_name.startswith(prefix + "."):
                threshold = self._module_numerics[prefix]
                break

        if event_level < threshold:
            raise structlog.DropEvent()
        return event_dict


def make_level_filter(default_level: str, module_levels: dict[str, str]) -> _LevelFilter:
    """Create a _LevelFilter for per-module log level overrides."""
    return _LevelFilter(default_level, module_levels)


def rename_event_to_message(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Rename structlog's 'event' key to canonical 'message' before JSON rendering.

    All four language loggers must emit 'message' as the message field.  structlog
    uses 'event' internally; this processor is inserted immediately before the
    JSONRenderer so the rename only affects the serialised output — all upstream
    processors (schema enforcement, PII sanitization, harden_input, etc.) still
    operate on 'event' as normal.
    """
    if "event" in event_dict:
        event_dict["message"] = event_dict.pop("event")
    return event_dict
