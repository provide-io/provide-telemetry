# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Non-otel mutation coverage for the block-level span helpers.

``span()`` / ``set_attrs()`` / ``record_exception()`` / ``_set_span_attr()`` are
exercised here with plain mock spans and a stubbed lifecycle (no real OTel), so
the mutation gate — which runs without the ``otel`` extra and deselects
``@otel`` tests — can kill these mutants. Real-SDK behaviour (ID correlation,
SDK status codes, governance) is validated separately in the ``@otel``-marked
``test_span.py``.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from provide.telemetry.tracing.span import _set_span_attr, record_exception, set_attrs, span

if TYPE_CHECKING:
    from collections.abc import Iterator


class _RecordingSpan:
    """A span that records ``set_attribute`` calls and nothing else."""

    def __init__(self) -> None:
        self.attrs: list[tuple[str, Any]] = []

    def set_attribute(self, key: str, value: Any) -> None:
        self.attrs.append((key, value))


# ── _set_span_attr coercion ──────────────────────────────────────────────


def test_set_span_attr_noop_when_span_has_no_setter() -> None:
    """A span without ``set_attribute`` is left untouched and never errors."""

    class _NoSetter: ...

    _set_span_attr(_NoSetter(), "k", 1)  # no raise, no setter invented


def test_set_span_attr_primitives_pass_through_unchanged() -> None:
    """str / int / float / bool are recorded verbatim, not stringified."""
    sp = _RecordingSpan()
    _set_span_attr(sp, "i", 7)
    _set_span_attr(sp, "s", "x")
    _set_span_attr(sp, "f", 1.5)
    _set_span_attr(sp, "b", True)
    assert sp.attrs == [("i", 7), ("s", "x"), ("f", 1.5), ("b", True)]


def test_set_span_attr_primitive_sequence_coerced_to_list() -> None:
    """Lists and tuples of primitives become a ``list`` (tuple is converted)."""
    sp = _RecordingSpan()
    _set_span_attr(sp, "lst", [1, 2, 3])
    _set_span_attr(sp, "tup", (4, 5))
    assert sp.attrs == [("lst", [1, 2, 3]), ("tup", [4, 5])]
    assert isinstance(sp.attrs[1][1], list)  # tuple -> list, not left a tuple


def test_set_span_attr_empty_sequence_recorded_as_list() -> None:
    """An empty sequence passes the primitive check and stays a list."""
    sp = _RecordingSpan()
    _set_span_attr(sp, "e", [])
    assert sp.attrs == [("e", [])]


def test_set_span_attr_mixed_sequence_is_stringified() -> None:
    """A sequence containing a non-primitive is stringified whole."""
    sentinel = object()
    sp = _RecordingSpan()
    _set_span_attr(sp, "mixed", [1, sentinel])
    assert sp.attrs == [("mixed", str([1, sentinel]))]


def test_set_span_attr_non_primitive_is_stringified() -> None:
    """A non-primitive, non-sequence value is stringified."""
    sentinel = object()
    sp = _RecordingSpan()
    _set_span_attr(sp, "o", sentinel)
    assert sp.attrs == [("o", str(sentinel))]


def test_set_span_attr_swallows_setter_errors() -> None:
    """A span whose ``set_attribute`` raises must not break the caller."""

    class _BadSpan:
        def set_attribute(self, _key: str, _value: object) -> None:
            raise RuntimeError("cannot set")

    _set_span_attr(_BadSpan(), "k", 1)  # no raise


# ── set_attrs ────────────────────────────────────────────────────────────


def test_set_attrs_records_non_none_and_drops_none() -> None:
    sp = _RecordingSpan()
    set_attrs(sp, a=1, b=None, c="x")
    assert sp.attrs == [("a", 1), ("c", "x")]


def test_set_attrs_safe_on_span_without_setter() -> None:
    class _NoSetter: ...

    set_attrs(_NoSetter(), a=1)  # no raise


# ── span() (lifecycle stubbed) ───────────────────────────────────────────


@pytest.fixture
def stub_open_span(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, Any], _RecordingSpan]:
    """Replace the shared ``_open_span`` lifecycle with a recording stub."""
    captured: dict[str, Any] = {}
    sp = _RecordingSpan()

    @contextmanager
    def _stub(name: str, scope: str | None = None) -> Iterator[Any]:
        captured["name"] = name
        captured["scope"] = scope
        yield sp

    # Reach the submodule via sys.modules: the package __init__ re-exports the
    # `span` function, shadowing the submodule attribute for normal access.
    monkeypatch.setattr(sys.modules["provide.telemetry.tracing.span"], "_open_span", _stub)
    return captured, sp


def test_span_opens_named_span_and_sets_non_none_attrs(
    stub_open_span: tuple[dict[str, Any], _RecordingSpan],
) -> None:
    captured, sp = stub_open_span
    with span("area.verb", primitive=7, skipped=None, seq=[1, 2]) as yielded:
        assert yielded is sp
    assert captured["name"] == "area.verb"
    assert sp.attrs == [("primitive", 7), ("seq", [1, 2])]  # None dropped


def test_span_propagates_body_exception(
    stub_open_span: tuple[dict[str, Any], _RecordingSpan],
) -> None:
    with pytest.raises(ValueError, match="boom"), span("op.fail"):
        raise ValueError("boom")


# ── record_exception (non-otel-reachable behaviour) ──────────────────────


def test_record_exception_calls_span_record_exception() -> None:
    calls: list[BaseException] = []

    class _Span:
        def record_exception(self, exc: BaseException) -> None:
            calls.append(exc)

    exc = ValueError("x")
    record_exception(_Span(), exc)
    assert calls == [exc]


def test_record_exception_safe_when_span_lacks_hooks() -> None:
    class _Bare: ...

    record_exception(_Bare(), ValueError("x"))  # no raise


def test_record_exception_swallows_record_errors() -> None:
    class _Span:
        def record_exception(self, _exc: BaseException) -> None:
            raise RuntimeError("nope")

    record_exception(_Span(), ValueError("x"))  # no raise


def test_record_exception_set_status_path_never_raises() -> None:
    """A span exposing ``set_status``: the OTel ``Status`` import is suppressed
    when the extra is absent (and the call is best-effort when present), so
    record_exception must never raise either way."""

    class _Span:
        def set_status(self, _status: object) -> None: ...

    record_exception(_Span(), ValueError("x"))  # no raise
