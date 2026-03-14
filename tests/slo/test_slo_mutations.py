# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests targeting surviving mutation-testing mutants in slo.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from undef.telemetry.backpressure import reset_queues_for_tests
from undef.telemetry.sampling import reset_sampling_for_tests
from undef.telemetry.slo import (
    _lazy_counter,
    _lazy_gauge,
    _lazy_histogram,
    _reset_slo_for_tests,
    classify_error,
    record_red_metrics,
    record_use_metrics,
)


@pytest.fixture(autouse=True)
def _reset_slo() -> None:
    """Reset cached SLO instruments and dependencies before each test."""
    reset_sampling_for_tests()
    reset_queues_for_tests()
    _reset_slo_for_tests()


# ---------- _lazy_counter ----------


def test_lazy_counter_passes_correct_name() -> None:
    c = _lazy_counter("my.counter", "My counter description")
    assert c.name == "my.counter"


def test_lazy_counter_passes_correct_description() -> None:
    """Kills mutant that replaces description with None or swaps args."""
    with patch("undef.telemetry.slo.counter") as mock_counter:
        mock_counter.return_value = mock_counter
        mock_counter.name = "x"
        _reset_slo_for_tests()
        _lazy_counter("x", "desc-value")
        mock_counter.assert_called_once_with("x", "desc-value")


def test_lazy_counter_caches_on_name() -> None:
    c1 = _lazy_counter("same.name", "desc1")
    c2 = _lazy_counter("same.name", "desc2")
    assert c1 is c2


# ---------- _lazy_histogram ----------


def test_lazy_histogram_passes_correct_name() -> None:
    h = _lazy_histogram("my.hist", "Hist desc", "ms")
    assert h.name == "my.hist"


def test_lazy_histogram_passes_correct_args() -> None:
    """Kills mutants that swap/drop name, description, or unit."""
    with patch("undef.telemetry.slo.histogram") as mock_hist:
        mock_hist.return_value = mock_hist
        mock_hist.name = "h"
        _reset_slo_for_tests()
        _lazy_histogram("h", "h-desc", "s")
        mock_hist.assert_called_once_with("h", "h-desc", "s")


def test_lazy_histogram_caches_on_name() -> None:
    h1 = _lazy_histogram("same", "d1", "ms")
    h2 = _lazy_histogram("same", "d2", "s")
    assert h1 is h2


# ---------- _lazy_gauge ----------


def test_lazy_gauge_passes_correct_name() -> None:
    g = _lazy_gauge("my.gauge", "Gauge desc", "%")
    assert g.name == "my.gauge"


def test_lazy_gauge_passes_correct_args() -> None:
    """Kills mutants that swap/drop name, description, or unit."""
    with patch("undef.telemetry.slo.gauge") as mock_gauge:
        mock_gauge.return_value = mock_gauge
        mock_gauge.name = "g"
        _reset_slo_for_tests()
        _lazy_gauge("g", "g-desc", "%")
        mock_gauge.assert_called_once_with("g", "g-desc", "%")


def test_lazy_gauge_caches_on_name() -> None:
    g1 = _lazy_gauge("same", "d1", "%")
    g2 = _lazy_gauge("same", "d2", "u")
    assert g1 is g2


# ---------- classify_error ----------


def test_classify_error_server_at_500() -> None:
    """Boundary test: status_code == 500 must be 'server'."""
    result = classify_error("ServerError", status_code=500)
    assert result == {"error_type": "server", "error_code": "500", "error_name": "ServerError"}


def test_classify_error_server_at_501() -> None:
    result = classify_error("BadGateway", status_code=501)
    assert result == {"error_type": "server", "error_code": "501", "error_name": "BadGateway"}


def test_classify_error_client_at_400() -> None:
    """Boundary test: status_code == 400 must be 'client'."""
    result = classify_error("BadRequest", status_code=400)
    assert result == {"error_type": "client", "error_code": "400", "error_name": "BadRequest"}


def test_classify_error_client_at_499() -> None:
    """status_code == 499 is client, not server."""
    result = classify_error("Timeout", status_code=499)
    assert result == {"error_type": "client", "error_code": "499", "error_name": "Timeout"}


def test_classify_error_internal_at_399() -> None:
    """status_code == 399 is below 400, should be 'internal'."""
    result = classify_error("Redirect", status_code=399)
    assert result == {"error_type": "internal", "error_code": "0", "error_name": "Redirect"}


def test_classify_error_internal_no_status() -> None:
    result = classify_error("RuntimeError")
    assert result == {"error_type": "internal", "error_code": "0", "error_name": "RuntimeError"}


def test_classify_error_internal_with_none() -> None:
    result = classify_error("ValueError", status_code=None)
    assert result == {"error_type": "internal", "error_code": "0", "error_name": "ValueError"}


def test_classify_error_exc_name_preserved() -> None:
    """Kills mutant that replaces exc_name with a constant."""
    for code in (None, 400, 500):
        result = classify_error("UniqueExc", status_code=code)
        assert result["error_name"] == "UniqueExc"


def test_classify_error_status_code_as_string() -> None:
    """Kills mutant that replaces str(status_code) with a constant."""
    r500 = classify_error("E", status_code=503)
    assert r500["error_code"] == "503"
    r400 = classify_error("E", status_code=418)
    assert r400["error_code"] == "418"


# ---------- record_red_metrics ----------


def test_record_red_metrics_increments_request_counter() -> None:
    record_red_metrics("/api", "GET", 200, 10.0)
    from undef.telemetry.slo import _counters

    req_counter = _counters.get("http.requests.total")
    assert req_counter is not None
    assert req_counter.value == 1


def test_record_red_metrics_no_error_counter_for_non_5xx() -> None:
    record_red_metrics("/api", "GET", 200, 10.0)
    from undef.telemetry.slo import _counters

    assert "http.errors.total" not in _counters


def test_record_red_metrics_error_counter_attrs_passed() -> None:
    """Kills .add(1, None) and .add(1, ) mutants on error counter."""
    with (
        patch("undef.telemetry.slo._lazy_counter") as mock_ctr,
        patch("undef.telemetry.slo._lazy_histogram") as mock_hist,
    ):
        captured_error_attrs: list[dict[str, str] | None] = []

        def fake_add(amount: int, attrs: dict[str, str] | None = None) -> None:
            captured_error_attrs.append(attrs)

        mock_ctr.return_value = mock_ctr
        mock_ctr.add = fake_add
        mock_hist.return_value = mock_hist
        mock_hist.record = lambda *a, **kw: None

        record_red_metrics("/err", "POST", 500, 50.0)

        # 2 add calls: requests.total + errors.total
        assert len(captured_error_attrs) == 2
        # Both should have attrs dict, not None
        assert captured_error_attrs[0] is not None
        assert captured_error_attrs[1] is not None
        assert captured_error_attrs[1]["route"] == "/err"


def test_record_red_metrics_histogram_attrs_passed() -> None:
    """Kills .record(duration_ms, None) and .record(duration_ms, ) mutants."""
    with (
        patch("undef.telemetry.slo._lazy_counter") as mock_ctr,
        patch("undef.telemetry.slo._lazy_histogram") as mock_hist,
    ):
        captured_hist_attrs: list[dict[str, str] | None] = []

        def fake_record(value: float, attrs: dict[str, str] | None = None) -> None:
            captured_hist_attrs.append(attrs)

        mock_ctr.return_value = mock_ctr
        mock_ctr.add = lambda *a, **kw: None
        mock_hist.return_value = mock_hist
        mock_hist.record = fake_record

        record_red_metrics("/api", "GET", 200, 42.5)

        assert len(captured_hist_attrs) == 1
        assert captured_hist_attrs[0] is not None
        assert captured_hist_attrs[0]["route"] == "/api"


def test_record_red_metrics_error_counter_for_500() -> None:
    """Boundary: status_code == 500 must trigger error counter."""
    record_red_metrics("/api", "POST", 500, 50.0)
    from undef.telemetry.slo import _counters

    err_counter = _counters.get("http.errors.total")
    assert err_counter is not None
    assert err_counter.value == 1


def test_record_red_metrics_error_counter_for_501() -> None:
    record_red_metrics("/api", "DELETE", 501, 50.0)
    from undef.telemetry.slo import _counters

    err_counter = _counters.get("http.errors.total")
    assert err_counter is not None
    assert err_counter.value == 1


def test_record_red_metrics_no_error_counter_for_499() -> None:
    """Boundary: 499 is not >= 500, no error counter."""
    record_red_metrics("/api", "GET", 499, 10.0)
    from undef.telemetry.slo import _counters

    assert "http.errors.total" not in _counters


def test_record_red_metrics_ws_skips_error_even_for_500() -> None:
    """WS method must not increment error counter even for status >= 500."""
    record_red_metrics("/ws", "WS", 500, 10.0)
    from undef.telemetry.slo import _counters

    assert "http.errors.total" not in _counters


def test_record_red_metrics_request_counter_value_exact() -> None:
    """Kills .add(1) -> .add(2) mutant by calling twice and checking cumulative value."""
    record_red_metrics("/api", "GET", 200, 10.0)
    record_red_metrics("/api", "GET", 200, 10.0)
    from undef.telemetry.slo import _counters

    req_counter = _counters["http.requests.total"]
    assert req_counter.value == 2


def test_record_red_metrics_records_histogram() -> None:
    record_red_metrics("/api", "GET", 200, 42.5)
    from undef.telemetry.slo import _histograms

    hist = _histograms.get("http.request.duration_ms")
    assert hist is not None
    assert hist.count == 1
    assert hist.total == 42.5


def test_record_red_metrics_attribute_values() -> None:
    """Verify exact attribute dict values to kill attribute-mutation mutants."""
    with (
        patch("undef.telemetry.slo._lazy_counter") as mock_ctr,
        patch("undef.telemetry.slo._lazy_histogram") as mock_hist,
    ):
        mock_ctr.return_value = mock_ctr
        mock_ctr.add = lambda *a, **kw: None
        mock_hist.return_value = mock_hist
        mock_hist.record = lambda *a, **kw: None

        record_red_metrics("/path", "PUT", 201, 5.0)

        # Check the attrs passed to the request counter
        calls = mock_ctr.call_args_list
        # First call: http.requests.total
        assert calls[0][0] == ("http.requests.total", "Total HTTP requests")
        # Histogram call
        mock_hist.assert_called_once_with("http.request.duration_ms", "HTTP request latency", "ms")


def test_record_red_metrics_counter_names_and_descriptions() -> None:
    """Verify exact name/description args to _lazy_counter and _lazy_histogram."""
    with patch("undef.telemetry.slo.counter") as mock_c, patch("undef.telemetry.slo.histogram") as mock_h:
        mock_c.return_value = mock_c
        mock_c.name = "n"
        mock_c.add = lambda *a, **kw: None
        mock_h.return_value = mock_h
        mock_h.name = "n"
        mock_h.record = lambda *a, **kw: None

        record_red_metrics("/x", "GET", 500, 1.0)

        # Verify counter calls include correct args
        c_calls = mock_c.call_args_list
        c_names = [call[0][0] for call in c_calls]
        c_descs = [call[0][1] for call in c_calls]
        assert "http.requests.total" in c_names
        assert "Total HTTP requests" in c_descs
        assert "http.errors.total" in c_names
        assert "Total HTTP errors" in c_descs

        # Verify histogram call
        mock_h.assert_called_once_with("http.request.duration_ms", "HTTP request latency", "ms")


def test_record_red_metrics_status_code_as_string_in_attrs() -> None:
    """Kills mutant that removes str() around status_code."""
    with (
        patch("undef.telemetry.slo._lazy_counter") as mock_ctr,
        patch("undef.telemetry.slo._lazy_histogram") as mock_hist,
    ):
        captured_attrs: list[dict[str, str]] = []

        def fake_add(amount: int, attrs: dict[str, str] | None = None) -> None:
            if attrs:
                captured_attrs.append(attrs)

        mock_ctr.return_value = mock_ctr
        mock_ctr.add = fake_add
        mock_hist.return_value = mock_hist
        mock_hist.record = lambda *a, **kw: None

        record_red_metrics("/x", "GET", 200, 1.0)

        assert len(captured_attrs) >= 1
        assert captured_attrs[0]["status_code"] == "200"
        assert captured_attrs[0]["route"] == "/x"
        assert captured_attrs[0]["method"] == "GET"


# ---------- record_use_metrics ----------


def test_record_use_metrics_creates_gauge() -> None:
    record_use_metrics("cpu", 75)
    from undef.telemetry.slo import _gauges

    g = _gauges.get("resource.utilization.percent")
    assert g is not None
    assert g.value == 75


def test_record_use_metrics_passes_resource_attr() -> None:
    """Verify the resource attribute is correctly passed."""
    with patch("undef.telemetry.slo._lazy_gauge") as mock_g:
        mock_g.return_value = mock_g
        mock_g.set = lambda *a, **kw: None
        record_use_metrics("memory", 60)

        mock_g.assert_called_once_with("resource.utilization.percent", "Resource utilization", "%")


def test_record_use_metrics_gauge_args() -> None:
    """Kills mutants that swap gauge name, description, or unit."""
    with patch("undef.telemetry.slo.gauge") as mock_gauge:
        mock_gauge.return_value = mock_gauge
        mock_gauge.name = "resource.utilization.percent"
        mock_gauge.set = lambda *a, **kw: None
        record_use_metrics("disk", 50)

        mock_gauge.assert_called_once_with("resource.utilization.percent", "Resource utilization", "%")


def test_record_use_metrics_resource_attribute_value() -> None:
    """Verify the exact attribute dict passed to gauge.set."""
    with patch("undef.telemetry.slo._lazy_gauge") as mock_g:
        captured: list[tuple[int, dict[str, str]]] = []

        def fake_set(value: int, attrs: dict[str, str] | None = None) -> None:
            captured.append((value, attrs or {}))

        mock_g.return_value = mock_g
        mock_g.set = fake_set
        record_use_metrics("network", 30)

        assert len(captured) == 1
        assert captured[0][0] == 30
        assert captured[0][1] == {"resource": "network"}


# ---------- _rebind / _reset ----------


def test_rebind_clears_all_caches() -> None:
    from undef.telemetry.slo import _counters, _gauges, _histograms, _rebind_slo_instruments

    _lazy_counter("a", "b")
    _lazy_histogram("c", "d", "e")
    _lazy_gauge("f", "g", "h")
    assert len(_counters) == 1
    assert len(_histograms) == 1
    assert len(_gauges) == 1

    _rebind_slo_instruments()
    assert len(_counters) == 0
    assert len(_histograms) == 0
    assert len(_gauges) == 0
