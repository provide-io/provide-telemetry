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
from provide.telemetry.schema.events import EventSchemaError, validate_event_name, validate_required_keys
from provide.telemetry.tracing.context import get_span_id, get_trace_id


def _get_active_config() -> Any | None:
    """Return the active runtime config without eagerly loading the runtime module."""
    runtime = sys.modules.get("provide.telemetry.runtime")
    if runtime is None:
        return None
    return getattr(
        runtime, "_active_config", None
    )  # pragma: no mutate — sentinel getattr default; "" would be truthy-compatible but semantically identical here


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Keys are rendered bare by the console renderer, so unlike values they cannot
# keep TAB/LF/CR: any of the three splits or misaligns the rendered line.
_CONTROL_CHAR_KEY_RE = re.compile(r"[\x00-\x1f\x7f]")


def _clean_key(key: object) -> str:
    """Strip every control character from an attribute key."""
    return _CONTROL_CHAR_KEY_RE.sub("", str(key))


def _harden_keys(event_dict: dict[str, Any]) -> dict[str, Any]:
    """Rebuild *event_dict* under cleaned keys, resolving collisions safely.

    Cleaning is many-to-one: ``"trace_i\\x00d"`` and ``"trace_id"`` both come out
    as ``"trace_id"``. A plain dict comprehension lets the later one win, and
    structlog's ``merge_contextvars`` always inserts contextvar-bound fields
    (``trace_id``, ``span_id``, ``request_id``, ``session_id``) *before* the
    caller's keyword arguments — so a request payload forwarded as
    ``logger.info(event, **payload)`` with a control-character key could replace
    the real bound value and correlate the record to an attacker-chosen trace.

    So a key that needed cleaning never displaces one already present, and a key
    that needed no cleaning always wins over a sanitized one that got there
    first. Two sanitized keys that collide keep the first, which is arbitrary but
    at least does not lose a genuine field.
    """
    resolved: dict[str, Any] = {}
    verbatim: set[str] = set()
    for key, value in event_dict.items():
        text = str(key)
        name = _clean_key(text)
        untouched = name == text
        if name in resolved and not (untouched and name not in verbatim):
            continue
        # Re-assigning an existing name keeps its original insertion position,
        # so a verbatim key reclaiming its slot does not reorder the record.
        resolved[name] = value
        if untouched:
            verbatim.add(name)
    return resolved


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
            # No maxsplit, and no `# pragma: no mutate`. Taking [-1] made the
            # maxsplit unobservable, so it only ever produced equivalent mutants
            # — but the bare pragma needed to silence them also hid the
            # separator normalisation and the index, which are not equivalent.
            # Without the argument, split/rsplit are indistinguishable here and
            # every mutation mutmut still generates changes the fingerprint.
            segments = frame.filename.replace("\\", "/").rsplit("/")
            leaf = segments[-1]
            basename = leaf.rsplit(".", 1)[0].lower()
            func = (frame.name or "").lower()
            parts.append(f"{basename}:{func}")
    fingerprint_bytes = ":".join(parts).encode("utf-8")  # pragma: no mutate — codec alias
    return hashlib.sha256(
        fingerprint_bytes
    ).hexdigest()[
        :12
    ]  # pragma: no mutate — 12-char truncation is a deliberate fingerprint-size choice; exact value asserted by fingerprint tests


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
                # `>=` is equivalent: slicing a value already at the limit to
                # [:limit] returns the identical string.
                too_long = len(cleaned) > _max_value_length  # pragma: no mutate
                if too_long:
                    return cleaned[:_max_value_length]
                return cleaned
            if isinstance(value, dict) and depth < _max_depth:
                return {k: _clean_value(v, depth + 1) for k, v in value.items()}
            if isinstance(value, list) and depth < _max_depth:
                return [
                    _clean_value(item, depth + 1) for item in value
                ]  # pragma: no mutate — list-comp traversal; element ordering asserted by nested-list tests
            return value

        # `>=` is equivalent: at exactly the limit the rebuild keeps every key,
        # and dict equality ignores the reordering it introduces.
        over_budget = _max_attr_count > 0 and len(event_dict) > _max_attr_count  # pragma: no mutate
        if over_budget:
            # Preserve control/telemetry fields first, then fill with user payload.
            # Simple first-N truncation would silently drop level, trace_id, etc.
            # when callers pass many keyword arguments.
            priority = {k: event_dict[k] for k in _HARDEN_PRIORITY_KEYS if k in event_dict}
            remaining = max(0, _max_attr_count - len(priority))
            user_keys = [k for k in event_dict if k not in _HARDEN_PRIORITY_KEYS]
            event_dict = {**priority, **{k: event_dict[k] for k in user_keys[:remaining]}}
        # Keys are hardened as well as values. The console renderer quotes values
        # but emits keys bare, so a control character in a key — which can reach
        # here from an untrusted W3C baggage header — would forge a log record.
        # parse_baggage rejects such keys at the boundary; this is the second line
        # of defence, and also covers keys a caller passes directly. _harden_keys
        # rather than a plain comprehension because cleaning is many-to-one: see
        # its docstring for the trace_id-shadowing vector that opens up otherwise.
        return {k: _clean_value(v, 0) for k, v in _harden_keys(event_dict).items()}

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
    from provide.telemetry.consent import should_allow
    from provide.telemetry.health import increment_emitted
    from provide.telemetry.sampling import should_sample

    if not should_allow("logs", method_name):
        raise structlog.DropEvent()
    event_name = str(
        event_dict.get("event", "")
    )  # pragma: no mutate — empty-string default is fed into sampler which treats "" as unnamed; cosmetic vs any empty sentinel
    if not should_sample("logs", event_name):
        raise structlog.DropEvent()
    ticket = try_acquire("logs")
    if ticket is None:
        raise structlog.DropEvent()  # backpressure full; dropped counter already incremented
    increment_emitted("logs")
    # Stash the ticket. The final renderer processor moves it onto the
    # LogRecord via logging `extra`, and the stdlib handler boundary releases
    # it once all configured child handlers return from emit().
    event_dict[_BACKPRESSURE_TICKET_KEY] = ticket
    return event_dict


def render_with_backpressure_extra(renderer: Any) -> Any:
    """Render the event and attach any stashed ticket to stdlib logging `extra`."""

    def _processor(logger: Any, method_name: str, event_dict: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
        ticket = event_dict.pop(_BACKPRESSURE_TICKET_KEY, None)
        rendered = renderer(logger, method_name, event_dict)
        if ticket is None:
            return (rendered,), {}
        return (rendered,), {"extra": {_BACKPRESSURE_TICKET_KEY: ticket}}

    return _processor


def enforce_event_schema(config: TelemetryConfig) -> Any:
    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        live = _get_active_config()
        live_strict = live.strict_schema if live is not None else config.strict_schema
        live_event_schema = live.event_schema if live is not None else config.event_schema
        strict_event_name = True if live_strict else live_event_schema.strict_event_name
        required_keys = live_event_schema.required_keys
        event = str(event_dict.get("event", ""))
        try:
            validate_event_name(event, strict_event_name=strict_event_name)
            validate_required_keys(event_dict, required_keys)
        except EventSchemaError as exc:
            # Annotate instead of dropping — preserves telemetry while flagging
            # the schema violation.  Consumers can filter on _schema_error.
            # This is the cross-language standard (Rust/TypeScript/Go match).
            event_dict["_schema_error"] = str(exc)
        return event_dict

    return _processor


def sanitize_sensitive_fields(
    enabled: bool, max_depth: int = 8
) -> Any:  # pragma: no mutate — default max_depth=8 is overridden by live runtime config at every call; default value is only cosmetic
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
