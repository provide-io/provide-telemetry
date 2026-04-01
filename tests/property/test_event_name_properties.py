# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from provide.telemetry.schema.events import EventSchemaError, event_name, validate_event_name

_segment_chars = "abcdefghijklmnopqrstuvwxyz0123456789_"  # pragma: allowlist secret
_segment = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)


@given(segments=st.lists(_segment, min_size=3, max_size=5))
def test_event_name_property_builds_valid_strict_name(segments: list[str]) -> None:
    with patch("provide.telemetry.runtime._is_strict_event_name", return_value=True):
        name = event_name(*segments)
    assert name == ".".join(segments)
    validate_event_name(name, strict_event_name=True)


@given(base=_segment)
def test_event_name_property_rejects_hyphenated_segment(base: str) -> None:
    bad = f"{base}-x"
    with patch("provide.telemetry.runtime._is_strict_event_name", return_value=True):
        try:
            event_name("auth", bad, "success")
        except EventSchemaError as exc:
            assert str(exc) == f"invalid event segment: segment[1]={bad}"
        else:
            msg = "event_name accepted hyphenated segment"
            raise AssertionError(msg)


@given(
    segment=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
        min_size=1,
        max_size=8,
    ).filter(lambda s: not s[0].islower() or any(ch not in _segment_chars for ch in s)),
)
def test_event_name_property_rejects_non_matching_domain(segment: str) -> None:
    with patch("provide.telemetry.runtime._is_strict_event_name", return_value=True):
        try:
            event_name(segment, "login", "success")
        except EventSchemaError as exc:
            assert str(exc) == f"invalid event segment: segment[0]={segment}"
        else:
            msg = "event_name accepted invalid domain"
            raise AssertionError(msg)
