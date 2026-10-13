# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Prometheus metrics config: the shared cases in spec/prometheus_fixtures.yaml plus edges."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from provide.telemetry.config import MetricsConfig, PrometheusConfig, TelemetryConfig
from provide.telemetry.exceptions import ConfigurationError


def _repo_root() -> Path:
    """The directory holding VERSION; mutmut runs these tests from a copy under mutants/."""
    return next(p for p in Path(__file__).resolve().parents if (p / "VERSION").exists())


_FIXTURES: dict[str, Any] = yaml.safe_load(
    (_repo_root() / "spec" / "prometheus_fixtures.yaml").read_text(encoding="utf-8")
)


def _readers(m: MetricsConfig) -> list[str]:
    return [name for name, on in (("otlp", m.otlp_reader_enabled), ("prometheus", m.prometheus_reader_enabled)) if on]


@pytest.mark.parametrize("case", _FIXTURES["exporter_selection"], ids=lambda c: c["id"])
def test_exporter_selection(case: dict[str, Any]) -> None:
    if case.get("error"):
        with pytest.raises(ConfigurationError):
            TelemetryConfig.from_env(case["env"])
        return
    metrics = TelemetryConfig.from_env(case["env"]).metrics
    assert _readers(metrics) == case["exporters"]
    assert metrics.prometheus_listener_enabled is case["listener"]
    assert list(metrics.exporter_warnings) == case.get("warnings", [])


@pytest.mark.parametrize(
    ("section", "env_key", "attr", "want_key"),
    [
        ("listener_path", "PROVIDE_METRICS_PROMETHEUS_PATH", "path", "path"),
        ("listener_port", "OTEL_EXPORTER_PROMETHEUS_PORT", "port", "port"),
        ("translation_strategy", "PROVIDE_METRICS_PROMETHEUS_TRANSLATION", "translation", "strategy"),
    ],
    ids=["path", "port", "translation"],
)
def test_single_setting_cases(section: str, env_key: str, attr: str, want_key: str) -> None:
    for case in _FIXTURES[section]:
        env = {} if case["value"] is None else {env_key: case["value"]}
        if case.get("error"):
            with pytest.raises(ConfigurationError):
                TelemetryConfig.from_env(env)
            continue
        assert getattr(TelemetryConfig.from_env(env).metrics.prometheus, attr) == case[want_key], case["id"]


def test_every_named_strategy_is_accepted() -> None:
    from provide.telemetry._config_prometheus import TRANSLATION_STRATEGIES

    for strategy in TRANSLATION_STRATEGIES:
        env = {"PROVIDE_METRICS_PROMETHEUS_TRANSLATION": strategy}
        assert TelemetryConfig.from_env(env).metrics.prometheus.translation == strategy


@pytest.mark.parametrize("port", [0, 1, 65534, 65535])
def test_port_boundaries(port: int) -> None:
    assert TelemetryConfig.from_env({"OTEL_EXPORTER_PROMETHEUS_PORT": str(port)}).metrics.prometheus.port == port


def test_defaults() -> None:
    metrics = TelemetryConfig.from_env({}).metrics
    assert metrics.exporters == ("otlp",)
    assert metrics.health_otlp is False
    assert metrics.prometheus == PrometheusConfig(
        listen="false",
        host="127.0.0.1",
        port=9464,
        path="/metrics",
        translation="UnderscoreEscapingWithSuffixes",
        scope_labels=False,
        target_info=True,
        web_config="",
    )


def test_scalar_settings_are_read_and_trimmed() -> None:
    metrics = TelemetryConfig.from_env(
        {
            "OTEL_EXPORTER_PROMETHEUS_HOST": " 0.0.0.0 ",
            "PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS": "true",
            "PROVIDE_METRICS_PROMETHEUS_TARGET_INFO": "false",
            "PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG": " /etc/web.yml ",
            "PROVIDE_METRICS_HEALTH_OTLP": "true",
            "PROVIDE_METRICS_PROMETHEUS_LISTEN": " TRUE ",
        }
    ).metrics
    p = metrics.prometheus
    assert (p.host, p.scope_labels, p.target_info, p.web_config, p.listen) == (
        "0.0.0.0",
        True,
        False,
        "/etc/web.yml",
        "true",
    )
    assert metrics.health_otlp is True


@pytest.mark.parametrize(
    "key",
    [
        "PROVIDE_METRICS_PROMETHEUS_SCOPE_LABELS",
        "PROVIDE_METRICS_PROMETHEUS_TARGET_INFO",
        "PROVIDE_METRICS_HEALTH_OTLP",
    ],
)
def test_invalid_bools_are_errors(key: str) -> None:
    with pytest.raises(ConfigurationError):
        TelemetryConfig.from_env({key: "maybe"})


def test_disabled_metrics_enable_nothing() -> None:
    m = MetricsConfig(enabled=False, exporters=("prometheus", "otlp"), prometheus=PrometheusConfig(listen="true"))
    assert not (m.prometheus_listener_enabled or m.prometheus_reader_enabled or m.otlp_reader_enabled)


def test_auto_without_prometheus_does_not_listen() -> None:
    m = MetricsConfig(exporters=("otlp",), prometheus=PrometheusConfig(listen="auto"))
    assert m.prometheus_listener_enabled is False
    assert m.prometheus_reader_enabled is False


@pytest.mark.parametrize(
    "kwargs",
    [{"listen": "sometimes"}, {"port": -1}, {"port": 65536}, {"path": "metrics"}, {"translation": "Legacy"}],
    ids=["listen", "port-low", "port-high", "path", "translation"],
)
def test_code_built_prometheus_config_is_validated(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ConfigurationError):
        PrometheusConfig(**kwargs)


def test_code_built_exporters_are_validated() -> None:
    with pytest.raises(ConfigurationError):
        MetricsConfig(exporters=("statsd",))


@pytest.mark.parametrize(
    ("env", "message"),
    [
        (
            {"OTEL_METRICS_EXPORTER": "otlp,statsd", "PROVIDE_TELEMETRY_STRICT_CONFIG": "true"},
            "PROVIDE_TELEMETRY_STRICT_CONFIG: OTEL_METRICS_EXPORTER: unknown exporter statsd, ignored",
        ),
        (
            {"OTEL_METRICS_EXPORTER": "none,console", "PROVIDE_TELEMETRY_STRICT_CONFIG": "1"},
            "PROVIDE_TELEMETRY_STRICT_CONFIG: "
            "OTEL_METRICS_EXPORTER: console is not supported by provide-telemetry, ignored; "
            "OTEL_METRICS_EXPORTER: none cannot be combined with other exporters, ignored; "
            "OTEL_METRICS_EXPORTER: no supported exporter left, using otlp",
        ),
        (
            {"PROVIDE_TELEMETRY_STRICT_CONFIG": "maybe"},
            "invalid boolean for PROVIDE_TELEMETRY_STRICT_CONFIG: 'maybe' (expected one of: 1,true,yes,on,0,false,no,off)",
        ),
        (
            {"OTEL_EXPORTER_PROMETHEUS_PORT": "http"},
            "OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got 'http'",
        ),
        (
            {"OTEL_EXPORTER_PROMETHEUS_PORT": "70000"},
            "OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got 70000",
        ),
        (
            {"PROVIDE_METRICS_PROMETHEUS_LISTEN": "maybe"},
            "PROVIDE_METRICS_PROMETHEUS_LISTEN: want false, true or auto, got 'maybe'",
        ),
        (
            {"PROVIDE_METRICS_PROMETHEUS_PATH": "metrics"},
            "PROVIDE_METRICS_PROMETHEUS_PATH: want a path starting with / and no query or fragment, got 'metrics'",
        ),
        (
            {"PROVIDE_METRICS_PROMETHEUS_TRANSLATION": "Legacy"},
            "PROVIDE_METRICS_PROMETHEUS_TRANSLATION: unknown strategy 'Legacy'",
        ),
    ],
    ids=[
        "exporter-strict-unknown",
        "exporter-strict-many",
        "strict-config-bool",
        "port-nan",
        "port-range",
        "listen",
        "path",
        "translation",
    ],
)
def test_error_messages_name_the_setting_and_value(env: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        TelemetryConfig.from_env(env)
    assert str(excinfo.value) == message


def test_code_built_exporter_error_names_the_value() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        MetricsConfig(exporters=("statsd",))
    assert str(excinfo.value) == "metrics exporters: unknown ['statsd']"


def test_none_alone_selects_no_exporter() -> None:
    assert TelemetryConfig.from_env({"OTEL_METRICS_EXPORTER": "none"}).metrics.exporters == ()


def test_strict_config_defaults_off_and_is_read() -> None:
    assert TelemetryConfig.from_env({}).strict_config is False
    assert TelemetryConfig.from_env({"PROVIDE_TELEMETRY_STRICT_CONFIG": "true"}).strict_config is True


def test_strict_config_leaves_a_clean_exporter_value_alone() -> None:
    cfg = TelemetryConfig.from_env({"OTEL_METRICS_EXPORTER": "none", "PROVIDE_TELEMETRY_STRICT_CONFIG": "true"})
    assert (cfg.metrics.exporters, cfg.metrics.exporter_warnings) == ((), ())


def test_parse_is_lenient_unless_strict() -> None:
    from provide.telemetry._config_prometheus import parse_metrics_exporters

    assert parse_metrics_exporters("statsd") == (
        ("otlp",),
        (
            "OTEL_METRICS_EXPORTER: unknown exporter statsd, ignored",
            "OTEL_METRICS_EXPORTER: no supported exporter left, using otlp",
        ),
    )
    assert parse_metrics_exporters(None) == (("otlp",), ())
    assert parse_metrics_exporters(" , ") == (("otlp",), ())
    with pytest.raises(ConfigurationError):
        parse_metrics_exporters("statsd", strict=True)
