# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Text exposition rendering, driven by stand-ins shaped like OTel MetricsData.

The renderer only reads attributes, so these plain classes (named like the OTel
data types it dispatches on) keep the tests independent of the otel extra; the
otel-marked test at the end checks the same path against the real SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from provide.telemetry.metrics import _prom_render as render
from provide.telemetry.metrics._prom_render import Family, RenderOptions


@dataclass
class Point:
    value: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    count: int = 0
    sum: float = 0.0
    bucket_counts: tuple[int, ...] = ()
    explicit_bounds: tuple[float, ...] = ()


@dataclass
class Sum:
    data_points: list[Point]
    is_monotonic: bool = True


@dataclass
class Gauge:
    data_points: list[Point]


@dataclass
class Histogram:
    data_points: list[Point]


@dataclass
class ExponentialHistogram:
    data_points: list[Point]


@dataclass
class Metric:
    name: str
    data: Any
    unit: str = ""
    description: str = ""


@dataclass
class Scope:
    name: str = "provide.telemetry"
    version: str | None = "1.2.3"


@dataclass
class ScopeMetrics:
    metrics: list[Metric]
    scope: Scope = field(default_factory=Scope)


@dataclass
class Resource:
    attributes: dict[str, Any] = field(default_factory=lambda: {"service.name": "svc"})


@dataclass
class ResourceMetrics:
    scope_metrics: list[ScopeMetrics]
    resource: Resource = field(default_factory=Resource)


@dataclass
class MetricsData:
    resource_metrics: list[ResourceMetrics]


def _data(*metrics: Metric, scope: Scope | None = None, resource: Resource | None = None) -> MetricsData:
    sm = ScopeMetrics(list(metrics), scope or Scope())
    return MetricsData([ResourceMetrics([sm], resource or Resource())])


def _text(
    data: Any,
    strategy: str = "UnderscoreEscapingWithSuffixes",
    scope_labels: bool = False,
    target_info: bool = True,
    utf8: bool = False,
) -> str:
    options = RenderOptions(strategy, scope_labels=scope_labels, target_info=target_info, utf8=utf8)
    return render.render(render.families_from(data, options))


def test_counter_gauge_and_updown_render_with_types_and_help() -> None:
    text = _text(
        _data(
            Metric("app.requests", Sum([Point(3, {"route": "/a"})]), description="Requests\nserved"),
            Metric("app.cpu", Gauge([Point(0.5)]), unit="1"),
            Metric("app.queue", Sum([Point(-2)], is_monotonic=False)),
        ),
        target_info=False,
    )
    assert text == (
        "# TYPE app_cpu_ratio gauge\n"
        "app_cpu_ratio 0.5\n"
        "# TYPE app_queue gauge\n"
        "app_queue -2\n"
        "# HELP app_requests_total Requests\\nserved\n"
        "# TYPE app_requests_total counter\n"
        'app_requests_total{route="/a"} 3\n'
    )


def test_histogram_buckets_are_cumulative_with_inf_sum_and_count() -> None:
    point = Point(attributes={"k": "v"}, count=6, sum=12.5, bucket_counts=(1, 2, 3), explicit_bounds=(0.5, 10.0))
    text = _text(_data(Metric("lat", Histogram([point]), unit="ms")), target_info=False)
    assert text.splitlines()[1:] == [
        'lat_milliseconds_bucket{k="v",le="0.5"} 1',
        'lat_milliseconds_bucket{k="v",le="10"} 3',
        'lat_milliseconds_bucket{k="v",le="+Inf"} 6',
        'lat_milliseconds_sum{k="v"} 12.5',
        'lat_milliseconds_count{k="v"} 6',
    ]


def test_target_info_and_scope_labels() -> None:
    text = _text(
        _data(Metric("c", Sum([Point(1)])), resource=Resource({"service.name": "svc", "host.name": "h1"})),
        scope_labels=True,
    )
    assert 'target_info{service_name="svc",host_name="h1"} 1' in text
    assert "# TYPE target_info gauge" in text
    assert 'c_total{otel_scope_name="provide.telemetry",otel_scope_version="1.2.3"} 1' in text


def test_scope_without_version_and_resource_without_attributes() -> None:
    text = _text(
        _data(Metric("c", Sum([Point(1)])), scope=Scope(version=None), resource=Resource({})), scope_labels=True
    )
    assert 'c_total{otel_scope_name="provide.telemetry"} 1' in text
    assert "target_info" not in text


def test_reserved_and_untranslatable_attributes_are_dropped_not_the_sample() -> None:
    text = _text(
        _data(Metric("c", Sum([Point(1, {"__internal": "x", "___": "y", "kept": "z"})]))),
        strategy="NoTranslation",
        utf8=True,
        target_info=False,
    )
    assert text.splitlines()[-1] == 'c{kept="z"} 1'


def test_escaping_rescues_a_double_underscore_key() -> None:
    text = _text(_data(Metric("c", Sum([Point(1, {"__internal": "x"})]))), target_info=False)
    assert text.splitlines()[-1] == 'c_total{_internal="x"} 1'


def test_unsupported_data_untranslatable_names_and_type_clashes_are_skipped() -> None:
    text = _text(
        _data(
            Metric("expo", ExponentialHistogram([Point(1)])),
            Metric("...", Gauge([Point(1)])),
            Metric("dup", Gauge([Point(1)])),
            Metric("dup", Sum([Point(2)], is_monotonic=False)),
            Metric("dup", Histogram([Point(count=1, sum=1.0, bucket_counts=(1,), explicit_bounds=())])),
        ),
        strategy="UnderscoreEscapingWithoutSuffixes",
        target_info=False,
    )
    assert text == "# TYPE dup gauge\ndup 1\ndup 2\n"


def test_utf8_names_render_quoted_when_negotiated() -> None:
    data = _data(Metric("app.requests", Sum([Point(1, {"http.route": 'a"b\\c'})])))
    text = _text(data, strategy="NoUTF8EscapingWithSuffixes", utf8=True, target_info=False)
    assert text == ('# TYPE "app.requests_total" counter\n{"app.requests_total","http.route"="a\\"b\\\\c"} 1\n')


def test_utf8_strategy_falls_back_to_escaping_for_other_scrapers() -> None:
    data = _data(Metric("app.requests", Sum([Point(1, {"http.route": "/a"})])))
    with_suffixes = _text(data, strategy="NoUTF8EscapingWithSuffixes", target_info=False)
    without = _text(data, strategy="NoTranslation", target_info=False)
    assert with_suffixes.splitlines()[-1] == 'app_requests_total{http_route="/a"} 1'
    assert without.splitlines()[-1] == 'app_requests{http_route="/a"} 1'


def test_empty_data_renders_nothing() -> None:
    assert _text(MetricsData([])) == ""
    assert _text(None) == ""
    assert render.render([Family("x", "gauge")]) == "# TYPE x gauge\n"


@pytest.mark.parametrize(
    ("accept", "want"),
    [
        (None, False),
        ("text/plain;version=0.0.4", False),
        ("application/openmetrics-text;version=1.0.0;escaping=allow-utf-8", False),
        ("application/openmetrics-text;q=0.6, text/plain; version=1.0.0; escaping=allow-utf-8;q=0.5", True),
        ("TEXT/PLAIN;ESCAPING=ALLOW-UTF-8", True),
    ],
)
def test_wants_utf8(accept: str | None, want: bool) -> None:
    assert render.wants_utf8(accept) is want


@pytest.mark.parametrize(
    ("value", "want"),
    [
        (3.0, "3"),
        (-2, "-2"),
        (41.5, "41.5"),
        (1e20, "1e+20"),
        (float("inf"), "+Inf"),
        (float("-inf"), "-Inf"),
        (float("nan"), "NaN"),
    ],
)
def test_format_value(value: float, want: str) -> None:
    assert render.format_value(value) == want


def test_effective_strategy() -> None:
    for strategy in ("UnderscoreEscapingWithSuffixes", "UnderscoreEscapingWithoutSuffixes"):
        assert render.effective_strategy(RenderOptions(strategy)) == strategy
    assert render.effective_strategy(RenderOptions("NoTranslation", utf8=True)) == "NoTranslation"
    assert render.effective_strategy(RenderOptions("NoUTF8EscapingWithSuffixes")) == "UnderscoreEscapingWithSuffixes"
    assert render.effective_strategy(RenderOptions("NoTranslation")) == "UnderscoreEscapingWithoutSuffixes"


@pytest.mark.otel
def test_renders_real_sdk_metrics_data() -> None:
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reader = InMemoryMetricReader()
    meter = MeterProvider(metric_readers=[reader]).get_meter("t")
    meter.create_counter("real.requests").add(2, {"route": "/a"})
    meter.create_histogram("real.latency", unit="ms").record(7)
    meter.create_gauge("real.cpu", unit="1").set(0.25)
    text = _text(reader.get_metrics_data(), target_info=False)
    assert 'real_requests_total{route="/a"} 2' in text
    assert "real_latency_milliseconds_count 1" in text
    assert "real_cpu_ratio 0.25" in text


def test_target_info_help_and_one_family_for_several_resources() -> None:
    data = MetricsData(
        [
            ResourceMetrics([ScopeMetrics([])], Resource({"service.name": "a"})),
            ResourceMetrics([ScopeMetrics([])], Resource({"service.name": "b"})),
        ]
    )
    assert _text(data) == (
        "# HELP target_info Target metadata\n"
        "# TYPE target_info gauge\n"
        'target_info{service_name="a"} 1\n'
        'target_info{service_name="b"} 1\n'
    )


def test_quotes_are_escaped_in_names_and_label_keys_but_not_in_help() -> None:
    family = Family('odd"name', "gauge", 'say "hi"\\now')
    family.samples.append(("", {'k"ey': "v", "plain": "w"}, 1.0))
    assert render.render([family]) == (
        '# HELP "odd\\"name" say "hi"\\\\now\n# TYPE "odd\\"name" gauge\n{"odd\\"name","k\\"ey"="v",plain="w"} 1\n'
    )


def test_utf8_label_key_in_legacy_named_sample() -> None:
    family = Family("plain", "gauge")
    family.samples.append(("", {"a.b": "1", "c": "2"}, 3.0))
    assert render.render([family]) == '# TYPE plain gauge\nplain{"a.b"="1",c="2"} 3\n'


def test_a_metric_named_target_info_keeps_its_family() -> None:
    text = _text(_data(Metric("target_info", Gauge([Point(5)]))))
    assert text == "# TYPE target_info gauge\ntarget_info 5\n"
