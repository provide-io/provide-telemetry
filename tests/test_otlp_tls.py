# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Unreadable OTLP TLS files keep that signal's exporter from being built."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from provide.telemetry import _otlp_tls
from provide.telemetry.config import TelemetryConfig
from tests.metrics.test_prom_listener import _PKI


@pytest.fixture(autouse=True)
def _clean() -> Any:
    _otlp_tls.take_problems()
    yield
    _otlp_tls.take_problems()


@pytest.fixture(scope="module")
def pki(tmp_path_factory: pytest.TempPathFactory) -> _PKI:
    return _PKI(tmp_path_factory.mktemp("pki"))


@pytest.fixture
def good(pki: _PKI) -> str:
    return str(pki.ca_file)


def test_nothing_configured_is_ready() -> None:
    assert _otlp_tls.unreadable("metrics", {}) is None
    assert _otlp_tls.unreadable("metrics", {"OTEL_EXPORTER_OTLP_CERTIFICATE": ""}) is None


@pytest.mark.parametrize("kind", ["CERTIFICATE", "CLIENT_CERTIFICATE", "CLIENT_KEY"])
def test_each_shared_file_is_checked(kind: str, tmp_path: Path, good: str) -> None:
    missing = str(tmp_path / "missing.pem")
    assert _otlp_tls.unreadable("traces", {f"OTEL_EXPORTER_OTLP_{kind}": good}) is None  # alone, a pair is not checked
    assert (
        _otlp_tls.unreadable("traces", {f"OTEL_EXPORTER_OTLP_{kind}": missing})
        == f"OTEL_EXPORTER_OTLP_{kind}={missing}: No such file or directory"
    )


@pytest.mark.parametrize("signal", ["logs", "traces", "metrics"])
def test_per_signal_wins_over_shared(signal: str, tmp_path: Path, good: str) -> None:
    missing = str(tmp_path / "missing.pem")
    upper = signal.upper()
    assert (
        _otlp_tls.unreadable(
            signal, {"OTEL_EXPORTER_OTLP_CERTIFICATE": missing, f"OTEL_EXPORTER_OTLP_{upper}_CERTIFICATE": good}
        )
        is None
    )
    assert (
        _otlp_tls.unreadable(
            signal, {"OTEL_EXPORTER_OTLP_CERTIFICATE": good, f"OTEL_EXPORTER_OTLP_{upper}_CLIENT_KEY": missing}
        )
        == f"OTEL_EXPORTER_OTLP_{upper}_CLIENT_KEY={missing}: No such file or directory"
    )
    # An empty per-signal variable means "not set", so the shared one applies.
    assert _otlp_tls.unreadable(
        signal, {"OTEL_EXPORTER_OTLP_CERTIFICATE": missing, f"OTEL_EXPORTER_OTLP_{upper}_CERTIFICATE": ""}
    ) == (f"OTEL_EXPORTER_OTLP_CERTIFICATE={missing}: No such file or directory")


def test_a_ca_file_without_certificates(tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.pem"
    garbage.write_bytes(b"not pem")
    assert (
        _otlp_tls.unreadable("metrics", {"OTEL_EXPORTER_OTLP_CERTIFICATE": str(garbage)})
        == f"OTEL_EXPORTER_OTLP_CERTIFICATE={garbage}: no PEM certificates"
    )


def test_client_certificate_and_key_must_pair(pki: _PKI) -> None:
    cert, key = str(pki.client_cert), str(pki.client_key)
    env = {"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE": cert, "OTEL_EXPORTER_OTLP_LOGS_CLIENT_KEY": key}
    assert _otlp_tls.unreadable("logs", env) is None
    env["OTEL_EXPORTER_OTLP_LOGS_CLIENT_KEY"] = str(pki.key_file)  # the server's key
    assert _otlp_tls.unreadable("logs", env) == (
        f"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE={cert}, OTEL_EXPORTER_OTLP_LOGS_CLIENT_KEY={pki.key_file}: "
        "KEY_VALUES_MISMATCH"
    )
    assert _otlp_tls.unreadable("logs", {"OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE": cert}) is None


def test_other_signals_files_are_ignored(tmp_path: Path) -> None:
    missing = str(tmp_path / "missing.pem")
    assert _otlp_tls.unreadable("logs", {"OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE": missing}) is None


def test_a_directory_is_unreadable(tmp_path: Path) -> None:
    problem = _otlp_tls.unreadable("logs", {"OTEL_EXPORTER_OTLP_CERTIFICATE": str(tmp_path)})
    # The reason is the OS's own: "Is a directory" on POSIX, "Permission denied" on Windows.
    with pytest.raises(OSError) as refused:
        tmp_path.open("rb")
    assert problem == f"OTEL_EXPORTER_OTLP_CERTIFICATE={tmp_path}: {refused.value.strerror}"


def test_tls_ready_records_logs_and_take_clears(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture, good: str
) -> None:
    missing = str(tmp_path / "missing.pem")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_CERTIFICATE", good)
    assert _otlp_tls.tls_ready("logs") is True
    assert _otlp_tls.take_problems() is None
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE", missing)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_CLIENT_KEY", missing)
    with caplog.at_level(logging.WARNING, logger=_otlp_tls.__name__):
        assert _otlp_tls.tls_ready("traces") is False
        assert _otlp_tls.tls_ready("metrics") is False
    traces, metrics = caplog.records
    assert traces.message == metrics.message == "otlp.tls_file_unreadable"
    assert traces.levelno == logging.WARNING
    assert traces.__dict__["signal"] == "traces" and metrics.__dict__["signal"] == "metrics"
    assert traces.__dict__["error"] == f"OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE={missing}: No such file or directory"
    assert _otlp_tls.take_problems() == (
        f"OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE={missing}: No such file or directory; "
        f"OTEL_EXPORTER_OTLP_METRICS_CLIENT_KEY={missing}: No such file or directory"
    )
    assert _otlp_tls.take_problems() is None


# ── each builder asks first ─────────────────────────────────────────────────


def _refuse(asked: list[str]) -> Any:
    def tls_ready(signal: str) -> bool:
        asked.append(signal)
        return False

    return tls_ready


def test_traces_exporter_is_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.tracing import provider as provider_mod
    from provide.telemetry.tracing.provider import _reset_tracing_for_tests

    _reset_tracing_for_tests()
    provider = Mock()
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL", True)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_trace_api",
        lambda: SimpleNamespace(set_tracer_provider=Mock(), get_tracer_provider=lambda: None),
    )
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_tracing_components",
        lambda: (SimpleNamespace(create=Mock(return_value="res")), Mock(return_value=provider), Mock(), exporter_cls),
    )
    asked: list[str] = []
    monkeypatch.setattr(provider_mod, "tls_ready", _refuse(asked))
    try:
        provider_mod.setup_tracing(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://trace"}))
        assert asked == ["traces"]
        exporter_cls.assert_not_called()
        provider.add_span_processor.assert_not_called()
    finally:
        _reset_tracing_for_tests()


def test_metrics_otlp_reader_is_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.metrics import provider as provider_mod
    from provide.telemetry.metrics.provider import _set_meter_for_test, setup_metrics

    provider_cls = Mock(return_value=Mock())
    exporter_cls = Mock(return_value="exporter")
    monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_metrics_api",
        lambda: SimpleNamespace(set_meter_provider=Mock(), get_meter=Mock(), get_meter_provider=lambda: None),
    )
    monkeypatch.setattr(
        provider_mod,
        "_load_otel_metrics_components",
        lambda: (provider_cls, SimpleNamespace(create=Mock(return_value="res")), Mock(), exporter_cls),
    )
    asked: list[str] = []
    monkeypatch.setattr(provider_mod, "tls_ready", _refuse(asked))
    try:
        setup_metrics(TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://metrics"}))
        assert asked == ["metrics"]
        exporter_cls.assert_not_called()
        assert provider_cls.call_args.kwargs["metric_readers"] == []  # the provider is still installed
    finally:
        _set_meter_for_test(None)


def test_logs_exporter_is_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.logger import core as core_mod

    exporter_cls = Mock()
    monkeypatch.setattr(
        core_mod,
        "_load_otel_logs_components",
        lambda: (Mock(), Mock(), Mock(), SimpleNamespace(create=Mock()), exporter_cls),
    )
    asked: list[str] = []
    monkeypatch.setattr(core_mod, "tls_ready", _refuse(asked))
    cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs"})
    handlers = core_mod._build_handlers(cfg, logging.INFO)
    assert asked == ["logs"]
    assert len(handlers) == 1
    exporter_cls.assert_not_called()


def test_setup_reports_the_problems_as_setup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry import get_health_snapshot, setup_telemetry, shutdown_telemetry
    from provide.telemetry import setup as setup_mod
    from provide.telemetry.setup import _reset_all_for_tests

    real_setup_tracing = vars(setup_mod)["setup_tracing"]

    def setup_tracing_with_a_bad_file(cfg: TelemetryConfig) -> None:
        _otlp_tls._problems.append("OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE=/x: No such file or directory")
        real_setup_tracing(cfg)

    _reset_all_for_tests()
    _otlp_tls._problems.append("stale from an earlier attempt")
    monkeypatch.setattr(setup_mod, "setup_tracing", setup_tracing_with_a_bad_file)
    config = TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "false"})
    try:
        setup_telemetry(config)
        assert get_health_snapshot().setup_error == (
            "OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE=/x: No such file or directory"
        )
        shutdown_telemetry()
        _reset_all_for_tests()
        monkeypatch.setattr(setup_mod, "setup_tracing", real_setup_tracing)
        setup_telemetry(config)
        assert get_health_snapshot().setup_error is None
    finally:
        shutdown_telemetry()
        _reset_all_for_tests()
