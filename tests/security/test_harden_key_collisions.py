# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Key cleaning must not let a forged key shadow a real one.

``_clean_key`` is many-to-one: ``"trace_i\\x00d"`` and ``"trace_id"`` both come
out as ``"trace_id"``. structlog's ``merge_contextvars`` inserts contextvar-bound
fields before the caller's keyword arguments, so with a plain dict comprehension
a request payload forwarded as ``logger.info(event, **payload)`` could replace
the bound ``trace_id`` with an attacker-chosen value — correlating the record to
the wrong trace and losing the real one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest

from provide.telemetry.logger.processors import _harden_keys, harden_input

_CONTROL_KEYS = ("event", "level", "trace_id", "span_id", "logger")


def _processor() -> Callable[[Any, str, dict[str, Any]], dict[str, Any]]:
    # harden_input is annotated `-> Any` so it can sit in structlog's processor
    # list; name the real shape here so the calls below type-check.
    return cast(
        "Callable[[Any, str, dict[str, Any]], dict[str, Any]]",
        harden_input(max_value_length=200, max_attr_count=0, max_depth=5),
    )


@pytest.mark.parametrize("field", _CONTROL_KEYS)
def test_a_forged_key_cannot_overwrite_a_control_field(field: str) -> None:
    """The forged key arrives second, as a caller's kwargs always do."""
    forged = field[:2] + "\x00" + field[2:]
    proc = _processor()

    result = proc(None, "info", {field: "genuine", forged: "FORGED"})

    assert result[field] == "genuine"


@pytest.mark.parametrize("field", _CONTROL_KEYS)
def test_the_genuine_key_wins_even_when_it_arrives_second(field: str) -> None:
    """Insertion order must not decide which value survives."""
    forged = field[:2] + "\x00" + field[2:]
    proc = _processor()

    result = proc(None, "info", {forged: "FORGED", field: "genuine"})

    assert result[field] == "genuine"


def test_two_sanitized_keys_that_collide_keep_the_first() -> None:
    """Arbitrary but lossless-by-one: neither is a genuine field."""
    proc = _processor()

    result = proc(None, "info", {"a\x00b": 1, "a\x01b": 2})

    assert result == {"ab": 1}


def test_a_dropped_collision_does_not_end_the_record() -> None:
    """The loop skips the colliding key and keeps going.

    Abandoning the rest of the event dict at the first collision would let one
    malformed attribute truncate every field a caller passed after it.
    """
    proc = _processor()

    result = proc(None, "info", {"a\x00b": 1, "a\x01b": 2, "kept": 3})

    assert result == {"ab": 1, "kept": 3}


def test_keys_needing_no_cleaning_are_untouched() -> None:
    proc = _processor()

    result = proc(None, "info", {"x": 1, "y": 2, "event": "ok"})

    assert result == {"x": 1, "y": 2, "event": "ok"}


def test_the_reclaimed_slot_keeps_its_original_position() -> None:
    """A verbatim key reclaiming a sanitized name must not reorder the record."""
    assert list(_harden_keys({"a\x00b": 1, "z": 3, "ab": 2})) == ["ab", "z"]
    assert _harden_keys({"a\x00b": 1, "z": 3, "ab": 2}) == {"ab": 2, "z": 3}


def test_non_string_keys_are_stringified_and_deduplicated() -> None:
    mixed: dict[Any, Any] = {1: "int", "1": "str"}
    assert _harden_keys(mixed) == {"1": "int"}


def test_nested_dict_keys_are_cleaned_at_every_depth() -> None:
    """Go, TypeScript and Rust clean keys at every level; Python must match.

    A dirty nested key would diverge the exported payload (and any receipt
    digest) from the other SDKs, and a newline in it forges a second rendered
    line just as a top-level key would.
    """
    proc = _processor()
    forged = "x\n2026-08-10 [error] payment.failed amount=9999"

    result = proc(None, "info", {"outer": {forged: 1, "in\x00ner": {"de\x7fep": 2}}})

    assert result == {"outer": {"x2026-08-10 [error] payment.failed amount=9999": 1, "inner": {"deep": 2}}}


def test_nested_collision_never_displaces_a_verbatim_key() -> None:
    """The top-level collision policy applies inside nested dicts too."""
    proc = _processor()

    first = proc(None, "info", {"outer": {"ab": "genuine", "a\x00b": "FORGED"}})
    second = proc(None, "info", {"outer": {"a\x00b": "FORGED", "ab": "genuine"}})

    assert first["outer"] == {"ab": "genuine"}
    assert second["outer"] == {"ab": "genuine"}


def test_dict_inside_a_list_has_its_keys_cleaned() -> None:
    proc = _processor()

    result = proc(None, "info", {"items": [{"k\x01ey": 1}]})

    assert result == {"items": [{"key": 1}]}
