# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import context as context_mod
from provide.telemetry.logger import processors as processors_mod
from provide.telemetry.logger.context import bind_context, clear_context, get_context, unbind_context
from provide.telemetry.logger.processors import add_standard_fields, apply_sampling, enforce_event_schema
from provide.telemetry.schema.events import EventSchemaError
from provide.telemetry.tracing.context import set_trace_context


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


def test_add_standard_fields_error_taxonomy_when_exc_name_present() -> None:
    cfg = TelemetryConfig.from_env({"PROVIDE_SLO_INCLUDE_ERROR_TAXONOMY": "true"})
    processor = add_standard_fields(cfg)
    out = processor(None, "error", {"event": "auth.login.error", "exc_name": "ValueError"})
    assert out["error_type"] == "internal"
    assert out["error_name"] == "ValueError"


def test_apply_sampling_drop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry import sampling as sampling_mod

    monkeypatch.setattr(sampling_mod, "should_sample", lambda _signal, _event: False)
    with pytest.raises(structlog.DropEvent):
        apply_sampling(None, "info", {"event": "auth.login.success"})


def test_apply_sampling_keep_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry import sampling as sampling_mod

    monkeypatch.setattr(sampling_mod, "should_sample", lambda _signal, _event: True)
    payload = {"event": "auth.login.success"}
    out = apply_sampling(None, "info", payload)
    assert out is payload


def test_enforce_event_schema_uses_empty_string_for_missing_event(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, bool]] = []
    required_calls: list[tuple[dict[str, object], tuple[str, ...]]] = []

    def _validate_event_name(name: str, strict_event_name: bool) -> None:
        seen.append((name, strict_event_name))

    def _validate_required_keys(data: dict[str, object], required_keys: tuple[str, ...]) -> None:
        required_calls.append((data, required_keys))

    monkeypatch.setattr(processors_mod, "validate_event_name", _validate_event_name)
    monkeypatch.setattr(processors_mod, "validate_required_keys", _validate_required_keys)
    cfg = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_STRICT_EVENT_NAME": "false"})
    processor = enforce_event_schema(cfg)
    payload: dict[str, object] = {"request_id": "r1"}
    out = processor(None, "info", payload)
    assert out is payload
    assert seen == [("", False)]
    assert required_calls == [(payload, ())]


def test_enforce_event_schema_required_keys_error_message() -> None:
    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_STRICT_SCHEMA": "true",
            "PROVIDE_TELEMETRY_REQUIRED_KEYS": "request_id,session_id",
        }
    )
    processor = enforce_event_schema(cfg)
    with pytest.raises(EventSchemaError, match=r"missing required keys: request_id, session_id"):
        processor(None, "info", {"event": "auth.login.success"})


def test_enforce_event_schema_enforces_required_keys_in_compat_mode() -> None:
    cfg = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_REQUIRED_KEYS": "request_id,session_id"})
    processor = enforce_event_schema(cfg)
    out = processor(None, "info", {"event": "auth.login.success"})
    assert out["event"] == "auth.login.success"


def test_enforce_event_schema_policy_matrix() -> None:
    compat_default = TelemetryConfig.from_env({})
    compat_relaxed = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_STRICT_EVENT_NAME": "false"})
    strict = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_STRICT_SCHEMA": "true"})

    relaxed_default = enforce_event_schema(compat_default)
    relaxed_explicit = enforce_event_schema(compat_relaxed)
    strict_name_strict_schema = enforce_event_schema(strict)

    # Default is now relaxed (strict_event_name=False)
    relaxed_default(None, "info", {"event": "bad event"})
    relaxed_explicit(None, "info", {"event": "bad event"})
    with pytest.raises(EventSchemaError, match="invalid event name"):
        strict_name_strict_schema(None, "info", {"event": "bad event"})


def test_save_context_preserves_current_values() -> None:
    """save_context must snapshot current context, not null it."""
    from provide.telemetry.logger.context import bind_context, get_context, reset_context, save_context

    bind_context(user="alice")
    token = save_context()
    bind_context(user="bob")
    assert get_context()["user"] == "bob"
    reset_context(token)
    assert get_context()["user"] == "alice"
