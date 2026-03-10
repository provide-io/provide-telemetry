# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Structlog processors."""

from __future__ import annotations

from typing import Any

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger.context import get_context
from undef.telemetry.schema.events import validate_event_name, validate_required_keys

_SENSITIVE_KEYS = {"password", "token", "authorization", "api_key", "secret"}


def merge_runtime_context(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict.update(get_context())
    return event_dict


def add_standard_fields(config: TelemetryConfig) -> Any:
    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("service", config.service_name)
        event_dict.setdefault("env", config.environment)
        event_dict.setdefault("version", config.version)
        return event_dict

    return _processor


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


def sanitize_sensitive_fields(enabled: bool) -> Any:
    def _processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        if not enabled:
            return event_dict
        redacted = dict(event_dict)
        for key in list(redacted.keys()):
            if key.lower() in _SENSITIVE_KEYS:
                redacted[key] = "***"
        return redacted

    return _processor
