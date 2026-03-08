# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import re

from hypothesis import given
from hypothesis import strategies as st

from undef.telemetry.config import _parse_bool, _parse_otlp_headers
from undef.telemetry.logger.processors import sanitize_sensitive_fields
from undef.telemetry.schema.events import EventSchemaError, validate_event_name

_EVENT_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


@given(value=st.one_of(st.none(), st.text()), default=st.booleans())
def test_parse_bool_fuzz_never_raises(value: str | None, default: bool) -> None:
    result = _parse_bool(value, default)
    assert isinstance(result, bool)


@given(raw=st.text(max_size=512))
def test_parse_otlp_headers_fuzz_never_raises(raw: str) -> None:
    parsed = _parse_otlp_headers(raw)
    assert isinstance(parsed, dict)


@given(
    event=st.dictionaries(
        keys=st.text(min_size=1, max_size=16),
        values=st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=32)),
        max_size=12,
    )
)
def test_sanitize_sensitive_fields_fuzz_redacts_known_keys(event: dict[str, object]) -> None:
    processor = sanitize_sensitive_fields(True)
    sanitized = processor(None, "info", event)
    for key, value in sanitized.items():
        if key.lower() in {"password", "token", "authorization", "api_key", "secret"}:
            assert value == "***"


@given(name=st.text(max_size=128))
def test_validate_event_name_fuzz_strict_behavior(name: str) -> None:
    is_valid = _EVENT_RE.match(name) is not None
    try:
        validate_event_name(name, strict_event_name=True)
    except EventSchemaError:
        assert not is_valid
    else:
        assert is_valid
