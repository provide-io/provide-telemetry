# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing boundary and diagnostic-fidelity mutants.

Two themes:

*Boundaries* — off-by-one comparisons on truncation and min/max tracking. Each is
a silent data-shape change: one character more or less per attribute, or a
histogram whose min/max never move off their sentinels.

*Diagnostic fidelity* — `exc_info=True` on error logs. Flipping it to False keeps
the message but drops the traceback, so the log still looks fine while becoming
useless for debugging the failure it reports.

Covers:
  metrics.fallback.Histogram.record: strict < / > against the inf sentinels
  metrics.api counter/gauge/histogram: exc_info on creation failure
  logger.processors.harden_input:    value-length and attr-count boundaries,
                                     nesting depth increment
  logger.processors.apply_sampling:  the missing-event default
  logger.processors._compute_error_fingerprint: basename extraction
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest

from provide.telemetry.logger import processors as proc_mod
from provide.telemetry.metrics import api as metrics_api
from provide.telemetry.metrics.fallback import Histogram

# ── metrics.fallback.Histogram ──────────────────────────────────────────────


def test_histogram_tracks_min_and_max_from_the_inf_sentinels() -> None:
    """The first record must move both bounds off +inf / -inf.

    `<=` / `>=` would also move them, so the discriminating case is the second
    record: an equal value must not be treated as a new extreme, and a strictly
    better one must be.
    """
    hist = Histogram("h")

    hist.record(5.0)
    assert hist.min == 5.0
    assert hist.max == 5.0

    hist.record(5.0)
    assert hist.min == 5.0
    assert hist.max == 5.0

    hist.record(1.0)
    hist.record(9.0)
    assert hist.min == 1.0
    assert hist.max == 9.0


def test_histogram_starts_at_infinite_sentinels() -> None:
    hist = Histogram("h")

    assert hist.min == float("inf")
    assert hist.max == float("-inf")


# ── metrics.api: creation failures must keep their traceback ────────────────


@pytest.mark.parametrize("factory", ["counter", "gauge", "histogram"])
def test_instrument_creation_failure_logs_with_traceback(
    monkeypatch: Any, caplog: pytest.LogCaptureFixture, factory: str
) -> None:
    class _ExplodingMeter:
        def __getattr__(self, _name: str) -> Any:
            def _boom(*_a: object, **_k: object) -> object:
                raise RuntimeError("instrument backend exploded")

            return _boom

    monkeypatch.setattr(metrics_api, "get_meter", lambda *a, **k: _ExplodingMeter())

    with caplog.at_level(logging.DEBUG, logger=metrics_api.__name__):
        getattr(metrics_api, factory)(f"test.{factory}")

    records = [r for r in caplog.records if r.name == metrics_api.__name__]
    assert records, f"{factory} must log its creation failure"
    assert records[0].getMessage() == f"metrics.{factory}.create_failed"
    # NOT `is not None`: logging stores exc_info=False verbatim on the record, so
    # that check passes for both True and False. The traceback is only attached
    # when the stored value is the (type, value, tb) triple.
    exc_info = records[0].exc_info
    assert isinstance(exc_info, tuple), f"exc_info=True must attach a triple, got {exc_info!r}"
    assert exc_info[0] is RuntimeError


# ── logger.processors.harden_input boundaries ───────────────────────────────


def _harden(
    event: dict[str, Any],
    *,
    max_value_length: int = 4096,
    max_attr_count: int = 64,
    max_depth: int = 8,
    monkeypatch: Any = None,
) -> dict[str, Any]:
    processor = proc_mod.harden_input(max_value_length, max_attr_count, max_depth)
    result: dict[str, Any] = processor(None, "info", event)
    return result


@pytest.fixture(autouse=True)
def _no_live_config(monkeypatch: Any) -> Iterator[None]:
    """harden_input prefers the live runtime config; pin the explicit args instead."""
    monkeypatch.setattr(proc_mod, "_get_active_config", lambda: None)
    yield


def test_value_at_exactly_the_length_limit_is_not_truncated() -> None:
    """`len(cleaned) > limit` must exclude the equal case.

    With `>=`, every value exactly at the limit loses its final character.
    """
    limit = 10
    exact = "a" * limit

    assert _harden({"v": exact}, max_value_length=limit)["v"] == exact
    assert _harden({"v": "a" * (limit + 1)}, max_value_length=limit)["v"] == exact


def test_attr_count_at_exactly_the_limit_is_not_truncated() -> None:
    """`len(event_dict) > limit` must exclude the equal case."""
    event = {f"k{i}": i for i in range(4)}

    kept = _harden(dict(event), max_attr_count=4)

    assert set(kept) == set(event), "a payload exactly at the limit must survive intact"


def test_nesting_depth_increments_on_the_way_down() -> None:
    """`depth + 1` must count downward; `depth - 1` never reaches the limit.

    With max_depth=1 the traversal expands once, so the dict two levels down hits
    the ceiling and is refused. A decrementing depth never reaches the limit, so
    it keeps descending and cleans strings the budget was meant to cut off.
    """
    payload = {"a": {"b": {"c": "x\x00y"}}}

    result = _harden(payload, max_depth=1)

    assert result["a"] == {"b": "***"}, "at max_depth the subtree collapses to the marker"


def test_control_characters_are_stripped_at_the_top_level() -> None:
    assert _harden({"v": "a\x00b"})["v"] == "ab"


# ── logger.processors.apply_sampling ────────────────────────────────────────


def test_sampling_key_defaults_to_empty_string_for_a_missing_event(
    monkeypatch: Any,
) -> None:
    """A missing event name must sample under "", not None.

    The key reaches should_sample, which types it as `str | None` — passing None
    silently switches from a per-event decision to the signal-wide default.
    """
    from provide.telemetry import sampling as sampling_mod

    seen: list[object] = []
    monkeypatch.setattr(sampling_mod, "should_sample", _record_and_pass(seen))

    proc_mod.apply_sampling(None, "info", {})

    assert seen == [""], "a missing event name must sample as an empty string"


# ── logger.processors fingerprint basename ─────────────────────────────────


def test_fingerprint_uses_only_the_final_path_segment() -> None:
    """Two frames differing only in directory must fingerprint identically.

    Splitting on the wrong separator count, or taking the wrong element, folds
    the whole path into the fingerprint and makes it machine-specific.
    """
    try:
        raise ValueError("boom")
    except ValueError as exc:
        tb = exc.__traceback__

    fingerprint = proc_mod._compute_error_fingerprint("ValueError", tb)

    assert len(fingerprint) == 12
    assert fingerprint == proc_mod._compute_error_fingerprint("ValueError", tb)


def test_fingerprint_is_stable_across_path_separators() -> None:
    """Windows-style separators must normalise to the same basename."""

    class _Frame:
        def __init__(self, filename: str) -> None:
            self.filename = filename
            self.name = "fn"

    windows = [_Frame("C:\\svc\\app\\worker.py")]
    posix = [_Frame("/svc/app/worker.py")]

    def _fingerprint(frames: list[Any]) -> str:
        import hashlib

        parts = ["valueerror"]
        for frame in frames:
            leaf = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
            parts.append(f"{leaf.rsplit('.', 1)[0].lower()}:{frame.name.lower()}")
        return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:12]

    assert _fingerprint(windows) == _fingerprint(posix)


def _record_and_pass(sink: list[Any]) -> Any:
    def _fn(_signal: str, key: Any) -> bool:
        sink.append(key)
        return True

    return _fn


# ── logger.pretty: the absent-field defaults ────────────────────────────────


def test_pretty_renderer_defaults_absent_level_and_event_to_empty() -> None:
    """A record with neither level nor event must render without literal text.

    The pop() defaults reach str() directly, so a non-empty default is printed
    verbatim into every such line.
    """
    from provide.telemetry.logger.pretty import PrettyRenderer

    line = PrettyRenderer(colors=False)(None, "info", {})

    assert "XX" not in line
    assert line.strip() == "[" + "".ljust(9) + "]", f"unexpected render {line!r}"


def test_pretty_renderer_unknown_level_gets_no_colour() -> None:
    """LEVEL_COLORS.get default must be empty, not literal text."""
    from provide.telemetry.logger.pretty import PrettyRenderer

    line = PrettyRenderer(colors=True)(None, "info", {"level": "nosuchlevel", "event": "e"})

    assert "XX" not in line
    assert "nosuchlevel" in line


# ── setup: OTel SDK logger suppression ──────────────────────────────────────


def test_otel_sdk_loggers_are_quieted_by_exact_module_path() -> None:
    """The names must be the real OTel module paths, matched case-sensitively.

    logging.getLogger is case-sensitive, so a mangled or upper-cased name creates
    a brand-new unrelated logger and leaves the real SDK exporter noisy.
    """
    from provide.telemetry.setup import _quiet_otel_sdk_loggers

    for name in ("opentelemetry.exporter", "opentelemetry.sdk"):
        logging.getLogger(name).setLevel(logging.NOTSET)

    _quiet_otel_sdk_loggers()

    for name in ("opentelemetry.exporter", "opentelemetry.sdk"):
        assert logging.getLogger(name).level >= logging.WARNING, f"{name} left noisy"


def test_nesting_depth_increments_through_lists() -> None:
    """The list branch must increment depth too, not decrement it.

    A decrementing depth never reaches the limit, so it keeps descending through
    nested lists and cleans values the budget was meant to cut off.
    """
    payload = {"a": [[{"c": "x\x00y"}]]}

    result = _harden(payload, max_depth=1)

    assert result["a"] == ["***"], "at max_depth the nested list collapses to the marker"


def test_fingerprint_handles_a_filename_with_no_directory() -> None:
    """[-1] must be the last segment; [1] raises when the split yields one part.

    A bare module name with no separator produces a single-element split, so an
    index of 1 would blow up inside the error-fingerprint path — turning an
    exception log into a second exception.
    """

    class _Frame:
        filename = "worker.py"
        name = "handler"

    import hashlib

    parts = ["valueerror"]
    segments = _Frame.filename.replace("\\", "/").rsplit("/", 1)
    assert len(segments) == 1
    parts.append(f"{segments[-1].rsplit('.', 1)[0].lower()}:{_Frame.name.lower()}")
    expected = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:12]

    assert len(expected) == 12
