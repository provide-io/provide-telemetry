# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Kill surviving mutants in ``logger/core.py`` for the OTLP logs setup path.

Targets ``_build_handlers`` and ``_make_otel_logging_handler``. The tests run
the real code path end-to-end with fake OTel components whose constructors
capture every argument they receive, so each mutation (argument swap, keyword
rename, dict-key text mutation, etc.) is detectable as a concrete assertion
failure.
"""

from __future__ import annotations

import logging
import warnings
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import core as core_mod
from provide.telemetry.logger.core import _reset_logging_for_tests


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset module-level singletons so one test can't leak into another."""
    _reset_logging_for_tests()


# ─────────────────────────────────────────────────────────────────────────────
# _build_handlers — end-to-end capture with a real run_with_resilience.
# ─────────────────────────────────────────────────────────────────────────────


class _RecordingExporter:
    """Captures the exact keyword arguments passed by the OTel build lambda."""

    instances: list[_RecordingExporter] = []

    def __init__(self, **kwargs: object) -> None:
        # Use **kwargs so omitted kwargs (mutations mutmut_37/38/39) show up as
        # missing keys — the default is deliberately NOT provided.
        self.kwargs = kwargs
        _RecordingExporter.instances.append(self)

    def export(self, *args: object, **kwargs: object) -> object:  # pragma: no cover
        return None


class _RecordingResource:
    created_with: list[object] = []

    @staticmethod
    def create(attrs: object) -> object:
        _RecordingResource.created_with.append(attrs)
        return SimpleNamespace(attrs=attrs)


class _RecordingProvider:
    instances: list[_RecordingProvider] = []

    def __init__(self, resource: object) -> None:
        self.resource = resource
        self.processors: list[object] = []
        _RecordingProvider.instances.append(self)

    def add_log_record_processor(self, processor: object) -> None:
        self.processors.append(processor)

    def shutdown(self) -> None:  # pragma: no cover
        return None


class _RecordingBatchProcessor:
    instances: list[_RecordingBatchProcessor] = []

    def __init__(self, exporter: object) -> None:
        self.exporter = exporter
        _RecordingBatchProcessor.instances.append(self)


class _RecordingLoggingHandler(logging.Handler):
    def __init__(self, **kwargs: object) -> None:
        # **kwargs so omitted positional/keyword mutations surface as missing
        # keys rather than TypeErrors we can't distinguish from the mutation.
        level = cast(int, kwargs.get("level", logging.NOTSET))
        super().__init__(level=level)
        self.kwargs = kwargs


def _patch_otel_pipeline(monkeypatch: pytest.MonkeyPatch, *, set_calls: list[object]) -> SimpleNamespace:
    """Install fake OTel components + capture set_logger_provider invocation.

    Returns the logs-API SimpleNamespace so tests can inspect what was invoked.
    """
    _RecordingExporter.instances = []
    _RecordingResource.created_with = []
    _RecordingProvider.instances = []
    _RecordingBatchProcessor.instances = []

    def _set_logger_provider(provider: object) -> None:
        set_calls.append(provider)

    logs_api_mod = SimpleNamespace(set_logger_provider=_set_logger_provider)
    sdk_logs_mod = SimpleNamespace(
        LoggerProvider=_RecordingProvider,
        LoggingHandler=_RecordingLoggingHandler,
    )
    sdk_logs_export_mod = SimpleNamespace(BatchLogRecordProcessor=_RecordingBatchProcessor)

    monkeypatch.setattr(
        core_mod,
        "_load_otel_logs_components",
        lambda: (logs_api_mod, sdk_logs_mod, sdk_logs_export_mod, _RecordingResource, _RecordingExporter),
    )
    monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: None)
    return logs_api_mod


@pytest.mark.otel
def test_build_handlers_otel_path_captures_every_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end exercise of the OTLP setup path with deep argument capture.

    This single test is the primary kill-vector for ``_build_handlers`` mutations:

    * resource.create dict keys (``service.name`` / ``service.version``)  — mutmut_20/21/22/23
    * resource.create argument is a real dict, not ``None``                — mutmut_18/19
    * LoggerProvider(resource=resource) — not provider=None, resource=None — mutmut_24/25
    * run_with_resilience signal is the literal "logs"                     — mutmut_27/31/32
    * lambda body constructs the exporter with correct kwargs              — mutmut_28/33/34/35/36/37/38/39/40
    * wrap_exporter("logs", raw_exporter) with both args                   — mutmut_42/43/44/45/46/47/48
    * add_log_record_processor receives the BatchLogRecordProcessor        — mutmut_49
    * BatchLogRecordProcessor receives the wrapped exporter                — mutmut_50
    * set_logger_provider receives the real provider (not None)            — mutmut_51
    * handlers.append receives a real handler (not None)                   — mutmut_52
    * _make_otel_logging_handler receives (sdk_logs_mod, provider, level, config) — mutmut_53..60
    * module-level _otel_log_provider is set to the provider, not None     — mutmut_61
    """
    # Do NOT monkeypatch run_with_resilience — we want signal validation to
    # happen for real so mutations of the "logs" literal (mutmut_27/31/32)
    # raise inside the resilience layer.

    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_SERVICE_NAME": "svc-under-test",
            "PROVIDE_TELEMETRY_VERSION": "7.8.9",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs.example:4318",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "X-API-Key=secret-value",
            "PROVIDE_EXPORTER_LOGS_TIMEOUT_SECONDS": "3.5",
        }
    )

    set_calls: list[object] = []
    _patch_otel_pipeline(monkeypatch, set_calls=set_calls)

    handlers = core_mod._build_handlers(cfg, logging.INFO)

    # handlers.append appended a real handler, not None (mutmut_52)
    assert len(handlers) == 2
    assert isinstance(handlers[0], logging.StreamHandler)
    handler = handlers[1]
    assert isinstance(handler, _RecordingLoggingHandler), f"handler was {handler!r}"

    # Resource.create received a real dict with the exact canonical keys
    # (mutmut_18/19/20/21/22/23)
    assert len(_RecordingResource.created_with) == 1
    resource_arg = _RecordingResource.created_with[0]
    assert isinstance(resource_arg, dict), (
        f"resource_cls.create must receive a dict, got {type(resource_arg)!r} "
        "(kills mutmut_18 resource=None and mutmut_19 create(None))"
    )
    assert resource_arg == {
        "service.name": "svc-under-test",
        "service.version": "7.8.9",
    }, (
        "resource dict keys must be exactly 'service.name' and 'service.version' "
        "(kills mutmut_20/21/22/23 dict-key text mutations)"
    )

    # Exactly one LoggerProvider was instantiated with the real resource
    # (mutmut_24 provider=None, mutmut_25 resource=None)
    assert len(_RecordingProvider.instances) == 1
    provider = _RecordingProvider.instances[0]
    assert provider.resource is not None
    assert getattr(provider.resource, "attrs", None) is resource_arg

    # The OTLP exporter was constructed with all three real kwargs
    # (mutmut_28 lambda=None, mutmut_33 lambda body=None,
    #  mutmut_34 endpoint=None, mutmut_35 headers=None, mutmut_36 timeout=None,
    #  mutmut_37 missing endpoint kwarg, mutmut_38 missing headers kwarg,
    #  mutmut_39 missing timeout kwarg, mutmut_40 validate(None)).
    assert len(_RecordingExporter.instances) == 1
    exporter = _RecordingExporter.instances[0]
    assert exporter.kwargs == {
        "endpoint": "http://logs.example:4318",
        "headers": {"X-API-Key": "secret-value"},
        "timeout": 3.5,
    }, (
        "OTLP exporter must receive endpoint/headers/timeout derived from the "
        "real config — not None, and all three kwargs present."
    )

    # wrap_exporter produced the real ResilientExporter around the exporter
    # and provider received exactly one BatchLogRecordProcessor wrapping it
    # (mutmut_42/43/44/45/46/47/48 for wrap_exporter,
    #  mutmut_49 add_log_record_processor(None),
    #  mutmut_50 BatchLogRecordProcessor(None)).
    assert len(_RecordingBatchProcessor.instances) == 1
    batch = _RecordingBatchProcessor.instances[0]
    assert batch.exporter is not None, "BatchLogRecordProcessor must receive the wrapped exporter (not None)"
    from provide.telemetry.resilient_exporter import ResilientExporter

    assert isinstance(batch.exporter, ResilientExporter), (
        f"wrap_exporter must return a ResilientExporter, got {type(batch.exporter)!r}"
    )
    assert batch.exporter._signal == "logs", (
        f"wrap_exporter must be called with signal='logs', got {batch.exporter._signal!r}"
    )
    assert batch.exporter._inner is exporter, "wrap_exporter must be called with the raw exporter, not None"
    assert provider.processors == [batch], "provider.add_log_record_processor must receive the BatchLogRecordProcessor"

    # set_logger_provider was called exactly once with the real provider
    # (mutmut_51 set_logger_provider(None)).
    assert set_calls == [provider], (
        f"logs_api_mod.set_logger_provider must be called with the real provider, got {set_calls!r}"
    )

    # The handler built by _make_otel_logging_handler received the real
    # sdk_logs_mod, provider, level, and config
    # (mutmut_53/54/55/56/57/58/59/60).
    assert handler.kwargs == {
        "level": logging.INFO,
        "logger_provider": provider,
    }, (
        "_make_otel_logging_handler must propagate level and provider from "
        "_build_handlers into the SDK LoggingHandler constructor."
    )

    # Module-level _otel_log_provider was assigned the live provider
    # (mutmut_61 _otel_log_provider = None).
    assert core_mod._otel_log_provider is provider, (
        "After successful setup, _otel_log_provider must be the live provider, not None (kills mutmut_61)."
    )


@pytest.mark.otel
def test_build_handlers_returns_early_when_raw_exporter_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When run_with_resilience returns None, no handler, processor, or global set occurs.

    This exercises the ``if raw_exporter is None: return handlers`` branch —
    important so that the later mutmut_42 "exporter = None" assertion is
    unambiguously about the post-None path.
    """
    cfg = TelemetryConfig.from_env(
        {
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs.example:4318",
            "PROVIDE_TELEMETRY_SERVICE_NAME": "svc",
            "PROVIDE_TELEMETRY_VERSION": "1.0",
        }
    )
    set_calls: list[object] = []
    _patch_otel_pipeline(monkeypatch, set_calls=set_calls)

    from provide.telemetry import resilience as resilience_mod

    monkeypatch.setattr(resilience_mod, "run_with_resilience", lambda _sig, _op: None)

    handlers = core_mod._build_handlers(cfg, logging.INFO)

    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    # No provider should be made public when the exporter probe fails
    assert core_mod._otel_log_provider is None
    assert set_calls == []
    # Provider is still constructed (before the None check) but must not be
    # exposed as the active global — this is the documented "failed
    # construction" safety net for shutdown_logging().


@pytest.mark.otel
def test_build_handlers_passes_level_to_handler_when_reusing_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reuse branch: handler receives (sdk_logs_mod, _otel_log_provider, level, config).

    Complements ``TestBuildHandlersConfigArg`` in ``test_logger_surviving_mutants``:
    that test checks ``config``; this one checks ``level`` and ``sdk_logs_mod``.
    """
    captured: list[tuple[object, object, object, object]] = []

    def _spy(sdk_mod: object, prov: object, lvl: object, cfg: object) -> logging.Handler:
        captured.append((sdk_mod, prov, lvl, cfg))
        return logging.NullHandler()

    monkeypatch.setattr(core_mod, "_make_otel_logging_handler", _spy)

    cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs:4318"})
    previous_provider = object()
    core_mod._otel_log_provider = previous_provider
    core_mod._otel_log_global_set = True
    core_mod._active_config = cfg

    mock_components = (MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
    monkeypatch.setattr(core_mod, "_load_otel_logs_components", lambda: mock_components)
    monkeypatch.setattr(core_mod, "_can_reuse_otel_log_provider", lambda _prev, _cur: True)

    core_mod._build_handlers(cfg, logging.WARNING)

    assert len(captured) == 1
    sdk_mod, prov, lvl, _cfg = captured[0]
    assert sdk_mod is mock_components[1], "sdk_logs_mod must be propagated"
    assert prov is previous_provider, "reuse branch must pass the existing provider"
    assert lvl == logging.WARNING, f"level must propagate, got {lvl!r}"


# ─────────────────────────────────────────────────────────────────────────────
# _make_otel_logging_handler — both branches, every kwarg.
# ─────────────────────────────────────────────────────────────────────────────


class TestMakeOtelLoggingHandlerInstrumentationBranch:
    """Kill mutants targeting the instrumentation-handler construction block.

    * mutmut_1: instrumentation_handler_cls = None  → falls through to SDK path
    * mutmut_3: level=None in ctor kwargs           → handler.level ends up 0/None
    * mutmut_4: logger_provider=None                → handler.logger_provider is None
    * mutmut_5: log_code_attributes=None            → handler.log_code_attributes is None
    * mutmut_6/7/8: kwarg omitted entirely          → TypeError or missing attribute
    """

    def _build_handler_cls(self) -> type[logging.Handler]:
        class _InstrumentationHandler(logging.Handler):
            def __init__(
                self,
                *,
                level: int,
                logger_provider: object,
                log_code_attributes: bool,
            ) -> None:
                # Strict kwargs — omitting any raises TypeError, which kills
                # the "missing kwarg" mutants (mutmut_6/7/8).
                super().__init__(level=level)
                self.logger_provider = logger_provider
                self.log_code_attributes = log_code_attributes

        return _InstrumentationHandler

    def test_instrumentation_branch_propagates_all_three_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills mutmut_1, 3, 4, 5, 6, 7, 8."""
        handler_cls = self._build_handler_cls()
        monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: handler_cls)

        cfg = TelemetryConfig.from_env({"PROVIDE_LOG_CODE_ATTRIBUTES": "true"})
        provider = object()
        sdk_logs_mod = SimpleNamespace()  # unused on this branch

        raw = core_mod._make_otel_logging_handler(sdk_logs_mod, provider, logging.WARNING, cfg)
        assert isinstance(raw, handler_cls)
        # level=level (kills mutmut_3 level=None)
        assert raw.level == logging.WARNING
        # logger_provider=provider (kills mutmut_4 logger_provider=None)
        assert getattr(raw, "logger_provider") is provider  # noqa: B009
        # log_code_attributes=config.logging.log_code_attributes (kills mutmut_5)
        assert getattr(raw, "log_code_attributes") is True  # noqa: B009

    def test_instrumentation_branch_propagates_false_log_code_attributes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ensure the log_code_attributes=None mutation (mutmut_5) is detected
        when the config value is False — ``None`` and ``False`` are both falsy
        under ``is`` only one way, so we check both truthy and falsy cases.
        """
        handler_cls = self._build_handler_cls()
        monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: handler_cls)
        cfg = TelemetryConfig()  # defaults: log_code_attributes=False
        handler = cast(
            Any,
            core_mod._make_otel_logging_handler(SimpleNamespace(), object(), logging.INFO, cfg),
        )
        assert handler.log_code_attributes is False, "log_code_attributes must be the real False, not None"

    def test_instrumentation_branch_not_taken_when_loader_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mutmut_1 makes the instrumentation_handler_cls always None; the
        branch is then never taken. The test below (SDK fallback) already
        asserts that the SDK path works, but we additionally assert that when
        ``_load_instrumentation_logging_handler`` truly returns None, the SDK
        ``LoggingHandler`` is what's built — this pins the ``is not None``
        check rather than its negation.
        """
        monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: None)

        class _SDKHandler(logging.Handler):
            def __init__(self, level: int, logger_provider: object) -> None:
                super().__init__(level=level)
                self.logger_provider = logger_provider

        sdk_logs_mod = SimpleNamespace(LoggingHandler=_SDKHandler)
        handler = core_mod._make_otel_logging_handler(sdk_logs_mod, object(), logging.DEBUG, TelemetryConfig())
        assert isinstance(handler, _SDKHandler)


class TestMakeOtelLoggingHandlerSdkFallbackBranch:
    """Kill mutants targeting the SDK fallback (warnings + LoggingHandler)."""

    def test_sdk_handler_receives_real_level_and_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The SDK ``LoggingHandler`` must receive the real level/provider."""
        monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: None)

        class _SDKHandler(logging.Handler):
            def __init__(self, level: int, logger_provider: object) -> None:
                super().__init__(level=level)
                self.logger_provider = logger_provider

        sdk_logs_mod = SimpleNamespace(LoggingHandler=_SDKHandler)
        sentinel_provider = object()
        handler = cast(
            Any,
            core_mod._make_otel_logging_handler(sdk_logs_mod, sentinel_provider, logging.ERROR, TelemetryConfig()),
        )
        assert handler.level == logging.ERROR
        assert handler.logger_provider is sentinel_provider

    def test_sdk_fallback_filters_deprecation_warnings_specifically(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``warnings.simplefilter`` must be called with ``("ignore", DeprecationWarning)``.

        Kills mutmut_10 (category=None) and mutmut_12 (category kwarg omitted).
        """
        monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: None)

        class _SDKHandler(logging.Handler):
            def __init__(self, level: int, logger_provider: object) -> None:
                super().__init__(level=level)

        sdk_logs_mod = SimpleNamespace(LoggingHandler=_SDKHandler)

        captured: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def _capture_simplefilter(*args: object, **kwargs: object) -> None:
            captured.append((args, kwargs))

        monkeypatch.setattr(warnings, "simplefilter", _capture_simplefilter)

        core_mod._make_otel_logging_handler(sdk_logs_mod, object(), logging.INFO, TelemetryConfig())

        assert captured, "warnings.simplefilter must be called"
        args, kwargs = captured[0]
        assert args == ("ignore", DeprecationWarning), (
            f"simplefilter must receive ('ignore', DeprecationWarning) — got args={args!r} "
            f"kwargs={kwargs!r} (kills mutmut_10 category=None and mutmut_12 missing category)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# _build_handlers — signal validation in run_with_resilience.
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildHandlersSignalValidation:
    """Kill "logs" string mutations by relying on ``run_with_resilience``'s
    signal whitelist (``{"logs", "traces", "metrics"}``).

    mutmut_27 makes the signal ``None``; mutmut_31 makes it ``"XXlogsXX"``;
    mutmut_32 makes it ``"LOGS"``. All three must fail at
    ``_validate_signal`` inside the real resilience layer. Since a failed
    construction propagates ``None`` back via the outer try/except in the
    resilience retry loop, the handler list ends with only the stderr one and
    _otel_log_provider stays None.

    We don't need to mock run_with_resilience here — the real one does the job.
    The same logic applies to ``wrap_exporter("logs", ...)`` — its internal
    use of the signal happens lazily (only on export failure), so we cover it
    via the ``_signal`` attribute assertion in the end-to-end test above.
    """

    def test_signal_is_exactly_logs_not_synonym(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If run_with_resilience is called with signal!='logs', it raises.

        We patch run_with_resilience with a validator that accepts only the
        exact string 'logs' — NOT 'LOGS', 'XXlogsXX', or None.
        """
        received_signals: list[object] = []

        def _strict(signal: object, op: object) -> object:
            received_signals.append(signal)
            # Accept only the exact literal
            if signal != "logs":
                raise AssertionError(
                    f"run_with_resilience got signal={signal!r}, expected 'logs'. "
                    "Kills mutmut_27 (None), mutmut_31 ('XXlogsXX'), mutmut_32 ('LOGS')."
                )
            return cast(Any, op)()

        from provide.telemetry import resilience as resilience_mod

        monkeypatch.setattr(resilience_mod, "run_with_resilience", _strict)

        cfg = TelemetryConfig.from_env(
            {
                "PROVIDE_TELEMETRY_SERVICE_NAME": "svc",
                "PROVIDE_TELEMETRY_VERSION": "1.0",
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs.example:4318",
            }
        )
        set_calls: list[object] = []
        _patch_otel_pipeline(monkeypatch, set_calls=set_calls)

        core_mod._build_handlers(cfg, logging.INFO)

        assert received_signals == ["logs"], (
            f"run_with_resilience must receive signal='logs' exactly once, got {received_signals!r}"
        )

    def test_wrap_exporter_signal_is_exactly_logs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kill mutmut_47 ('XXlogsXX') and mutmut_48 ('LOGS') for wrap_exporter.

        We patch wrap_exporter to assert on its signal argument directly.
        """
        received_signals: list[object] = []

        def _strict_wrap(signal: object, inner: object) -> object:
            received_signals.append(signal)
            return inner  # passthrough to keep the test simple

        # Patch at the import site — _build_handlers imports wrap_exporter
        # from resilient_exporter inside the function, so we patch there.
        from provide.telemetry import resilient_exporter as rex

        monkeypatch.setattr(rex, "wrap_exporter", _strict_wrap)

        # Also bypass real run_with_resilience so we get past it to wrap_exporter.
        from provide.telemetry import resilience as resilience_mod

        monkeypatch.setattr(resilience_mod, "run_with_resilience", lambda _sig, op: op())

        cfg = TelemetryConfig.from_env(
            {
                "PROVIDE_TELEMETRY_SERVICE_NAME": "svc",
                "PROVIDE_TELEMETRY_VERSION": "1.0",
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs.example:4318",
            }
        )
        set_calls: list[object] = []
        _patch_otel_pipeline(monkeypatch, set_calls=set_calls)

        core_mod._build_handlers(cfg, logging.INFO)

        assert received_signals == ["logs"], (
            f"wrap_exporter must be called with signal='logs' exactly, got {received_signals!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# _build_handlers — validate_otlp_endpoint must see the real endpoint.
# ─────────────────────────────────────────────────────────────────────────────


def test_build_handlers_validates_real_endpoint_not_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kill mutmut_40: ``validate_otlp_endpoint(None)``.

    With ``None``, ``validate_otlp_endpoint`` raises ``ValueError`` inside the
    lambda. The real ``run_with_resilience`` will swallow that and return
    ``None``, so the exporter wouldn't be built. We make sure the validator
    sees the real endpoint string.
    """
    received_endpoints: list[object] = []

    def _spy_validate(endpoint: object) -> object:
        received_endpoints.append(endpoint)
        return endpoint

    monkeypatch.setattr(core_mod, "validate_otlp_endpoint", _spy_validate)

    from provide.telemetry import resilience as resilience_mod

    monkeypatch.setattr(resilience_mod, "run_with_resilience", lambda _sig, op: op())

    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_SERVICE_NAME": "svc",
            "PROVIDE_TELEMETRY_VERSION": "1.0",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs.example:4318",
        }
    )
    set_calls: list[object] = []
    _patch_otel_pipeline(monkeypatch, set_calls=set_calls)

    core_mod._build_handlers(cfg, logging.INFO)

    assert received_endpoints == ["http://logs.example:4318"], (
        f"validate_otlp_endpoint must receive the real endpoint string, got {received_endpoints!r} (kills mutmut_40)"
    )
