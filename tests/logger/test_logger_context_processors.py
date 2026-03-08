# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import pytest

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger import context as context_mod
from undef.telemetry.logger import processors as processors_mod
from undef.telemetry.logger.context import bind_context, clear_context, get_context, unbind_context
from undef.telemetry.logger.processors import add_standard_fields, enforce_event_schema
from undef.telemetry.schema.events import EventSchemaError


def test_context_unbind_missing_key_is_noop_and_keeps_dict_state() -> None:
    clear_context()
    bind_context(request_id="rid")
    unbind_context("missing")
    assert get_context() == {"request_id": "rid"}
    assert context_mod._context.get() == {"request_id": "rid"}


def test_clear_context_sets_empty_dict_state() -> None:
    bind_context(request_id="rid")
    clear_context()
    assert get_context() == {}
    assert context_mod._context.get() == {}


def test_add_standard_fields_sets_exact_expected_keys() -> None:
    cfg = TelemetryConfig(service_name="svc", environment="prod", version="9.9.9")
    processor = add_standard_fields(cfg)
    out = processor(None, "info", {"event": "auth.login.success"})
    assert out["service"] == "svc"
    assert out["env"] == "prod"
    assert out["version"] == "9.9.9"
    assert "ENV" not in out
    assert "VERSION" not in out
    assert "XXenvXX" not in out
    assert "XXversionXX" not in out


def test_enforce_event_schema_uses_empty_string_for_missing_event(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, bool]] = []
    required_calls: list[tuple[dict[str, object], tuple[str, ...]]] = []

    def _validate_event_name(name: str, strict_event_name: bool) -> None:
        seen.append((name, strict_event_name))

    def _validate_required_keys(data: dict[str, object], required_keys: tuple[str, ...]) -> None:
        required_calls.append((data, required_keys))

    monkeypatch.setattr(processors_mod, "validate_event_name", _validate_event_name)
    monkeypatch.setattr(processors_mod, "validate_required_keys", _validate_required_keys)
    cfg = TelemetryConfig.from_env({"UNDEF_TELEMETRY_STRICT_EVENT_NAME": "false"})
    processor = enforce_event_schema(cfg)
    payload: dict[str, object] = {"request_id": "r1"}
    out = processor(None, "info", payload)
    assert out is payload
    assert seen == [("", False)]
    assert required_calls == [(payload, ())]


def test_enforce_event_schema_required_keys_error_message() -> None:
    cfg = TelemetryConfig.from_env({"UNDEF_TELEMETRY_REQUIRED_KEYS": "request_id,session_id"})
    processor = enforce_event_schema(cfg)
    with pytest.raises(EventSchemaError, match=r"missing required keys: request_id, session_id"):
        processor(None, "info", {"event": "auth.login.success"})
