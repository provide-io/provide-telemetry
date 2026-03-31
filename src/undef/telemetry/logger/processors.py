# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
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

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger.context import get_context
from undef.telemetry.pii import sanitize_payload
from undef.telemetry.sampling import should_sample
from undef.telemetry.schema.events import validate_event_name, validate_required_keys
from undef.telemetry.tracing.context import get_span_id, get_trace_id

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

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


def merge_runtime_context(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict.update(get_context())
    trace_id = get_trace_id()
    span_id = get_span_id()
    if trace_id is not None:
        event_dict["trace_id"] = trace_id
    if span_id is not None:
        event_dict["span_id"] = span_id
    return event_dict


def _compute_error_fingerprint(exc_type: str, tb: types.TracebackType | None) -> str:
    """Generate a stable 12-char hex fingerprint from exception type + top 3 frames."""
    parts = [exc_type.lower()]
    if tb is not None:
        for frame in traceback.extract_tb(tb)[-3:]:
            leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
            basename = leaf.rsplit(".", 1)[0].lower()
            func = (frame.name or "").lower()
            parts.append(f"{basename}:{func}")
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:12]


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

    def _clean_value(value: object, depth: int) -> object:
        if isinstance(value, str):
            cleaned = _CONTROL_CHAR_RE.sub("", value)
            if len(cleaned) > max_value_length:
                return cleaned[:max_value_length]
            return cleaned
        if isinstance(value, dict) and depth < max_depth:
            return {k: _clean_value(v, depth + 1) for k, v in value.items()}
        if isinstance(value, list) and depth < max_depth:
            return [_clean_value(item, depth + 1) for item in value]
        return value

    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        if max_attr_count > 0 and len(event_dict) > max_attr_count:
            keys = list(event_dict)[:max_attr_count]
            event_dict = {k: event_dict[k] for k in keys}
        return {k: _clean_value(v, 0) for k, v in event_dict.items()}

    return _processor


def add_standard_fields(config: TelemetryConfig) -> Any:
    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("service", config.service_name)
        event_dict.setdefault("env", config.environment)
        event_dict.setdefault("version", config.version)
        if config.slo.include_error_taxonomy and "error_type" not in event_dict and "exc_name" in event_dict:
            from undef.telemetry.slo import classify_error  # lazy: avoid loading metrics at logging config time

            status_code = event_dict.get("status_code")
            typed_status = status_code if isinstance(status_code, int) else None
            event_dict.update(classify_error(str(event_dict["exc_name"]), typed_status))
        return event_dict

    return _processor


def apply_sampling(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_name = str(event_dict.get("event", ""))
    if should_sample("logs", event_name):
        return event_dict
    return {"event": "telemetry.log.dropped", "dropped_event": event_name}


def enforce_event_schema(config: TelemetryConfig) -> Any:
    # strict_schema is authoritative: strict mode always enforces both checks.
    # compat mode keeps event-name policy configurable and skips required-key hard failures.
    strict_event_name = True if config.strict_schema else config.event_schema.strict_event_name
    required_keys = config.event_schema.required_keys if config.strict_schema else ()

    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event = str(event_dict.get("event", ""))
        validate_event_name(event, strict_event_name=strict_event_name)
        validate_required_keys(event_dict, required_keys)
        return event_dict

    return _processor


def sanitize_sensitive_fields(enabled: bool, max_depth: int = 8) -> Any:
    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        return sanitize_payload(event_dict, enabled, max_depth=max_depth)

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
            if logger_name.startswith(prefix):
                threshold = self._module_numerics[prefix]
                break

        if event_level < threshold:
            raise structlog.DropEvent()
        return event_dict


def make_level_filter(default_level: str, module_levels: dict[str, str]) -> _LevelFilter:
    """Create a _LevelFilter for per-module log level overrides."""
    return _LevelFilter(default_level, module_levels)
