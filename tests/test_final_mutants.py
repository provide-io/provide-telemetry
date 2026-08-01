# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing the last surviving mutants.

Covers:
  logger.pretty.PrettyRenderer:         the colors default
  logger.processors fingerprint:        segments[-1] on a directory-less filename
  logger.core._setup_emergency_fallback: warning stacklevel
  logger.core._configure_logging_inner:  the pretty value colour reaches the renderer
  tracing.provider.setup_tracing:        the resource reaches the no-sampler branch
"""

from __future__ import annotations

import contextlib
import warnings
from typing import Any

import pytest

from provide.telemetry.logger import core as core_mod
from provide.telemetry.logger import processors as proc_mod
from provide.telemetry.logger.pretty import PrettyRenderer


def test_pretty_renderer_defaults_to_colour_on() -> None:
    """The default must be True; call sites that omit it expect ANSI output.

    A False default silently strips colour from every renderer built without an
    explicit flag.
    """
    line = PrettyRenderer()(None, "info", {"level": "error", "event": "boom"})

    assert "\x1b[" in line, f"expected ANSI colour in {line!r}"


def test_fingerprint_handles_a_frame_with_no_directory_separator() -> None:
    """segments[-1] must be the last element; [1] blows up on a one-part split.

    A filename with no "/" splits into a single element, so an index of 1 raises
    IndexError inside the error path — turning an exception log into a second
    exception. compile() lets us produce exactly such a frame.
    """
    code = compile("raise ValueError('boom')", "worker.py", "exec")
    try:
        exec(code, {})
    except ValueError as exc:
        tb = exc.__traceback__

    fingerprint = proc_mod._compute_error_fingerprint("ValueError", tb)

    assert len(fingerprint) == 12
    assert fingerprint.isalnum()


def test_emergency_fallback_warning_blames_the_caller(monkeypatch: Any) -> None:
    """stacklevel=3 points past the fallback helper to the real origin.

    Captured off warnings.warn rather than the recorded frame: mutmut's
    trampoline adds a stack frame, so frame identity shifts under mutation.
    """
    calls: list[dict[str, Any]] = []

    def fake_warn(message: object, category: object = None, stacklevel: int = 1, **kw: Any) -> None:
        calls.append({"message": str(message), "category": category, "stacklevel": stacklevel})

    monkeypatch.setattr(warnings, "warn", fake_warn)

    core_mod._setup_emergency_fallback(RuntimeError("setup blew up"))

    fallback = [c for c in calls if "emergency stderr fallback" in c["message"]]
    assert len(fallback) == 1, f"expected one fallback warning, got {calls!r}"
    assert fallback[0]["category"] is RuntimeWarning
    assert fallback[0]["stacklevel"] == 3
    assert "setup blew up" in fallback[0]["message"]


def test_pretty_value_colour_reaches_the_renderer(monkeypatch: Any) -> None:
    """The configured value colour must be resolved and passed through.

    Dropping it to None (or passing the unresolved config field) makes every
    rendered value lose its colour while the key keeps its own.
    """
    captured: dict[str, Any] = {}

    class _Spy(PrettyRenderer):
        def __init__(self, **kw: Any) -> None:
            captured.update(kw)
            super().__init__(**kw)

    monkeypatch.setattr(core_mod, "PrettyRenderer", _Spy)

    from provide.telemetry.config import LoggingConfig, TelemetryConfig
    from provide.telemetry.logger.pretty import resolve_color

    cfg = TelemetryConfig(logging=LoggingConfig(fmt="pretty", pretty_key_color="cyan", pretty_value_color="red"))
    core_mod._configure_logging_inner(cfg)

    assert captured, "the pretty renderer must be constructed for fmt=pretty"
    assert captured["value_color"] == resolve_color("red")
    assert captured["value_color"] != ""
    assert captured["key_color"] == resolve_color("cyan")


def test_tracer_provider_receives_the_resource_without_a_sampler(monkeypatch: Any) -> None:
    """The no-sampler branch must still pass the built resource.

    provider_cls(resource=None) drops service.name/env/version from every span,
    which is invisible until someone tries to filter by service in the backend.
    """
    from provide.telemetry.config import TelemetryConfig
    from provide.telemetry.tracing import provider as tp_mod

    seen: list[dict[str, Any]] = []

    class _FakeProvider:
        def __init__(self, **kw: Any) -> None:
            seen.append(kw)

        def add_span_processor(self, _p: object) -> None:
            return None

    # Another test in the suite may have left a provider installed, in which case
    # setup_tracing returns before constructing anything.
    tp_mod.shutdown_tracing()
    monkeypatch.setattr(tp_mod, "_provider_configured", False)

    sentinel_resource = object()
    monkeypatch.setattr(tp_mod, "_load_otel_tracing_components", lambda: (None, _FakeProvider, None, None))
    monkeypatch.setattr(tp_mod, "_load_otel_trace_api", lambda: object())
    monkeypatch.setattr("provide.telemetry._otel.build_otel_trace_sampler", lambda rate: None)
    monkeypatch.setattr(tp_mod, "build_resource", lambda cfg, cls: sentinel_resource)

    cfg = TelemetryConfig()
    # Provider construction is what is under test; the OTLP wiring that follows
    # is not stubbed and may raise.
    with contextlib.suppress(Exception):
        tp_mod.setup_tracing(cfg)

    assert seen, "the provider must be constructed"
    assert seen[0].get("resource") is sentinel_resource
    assert "sampler" not in seen[0], "no sampler was available for this run"


@pytest.fixture(autouse=True)
def _reset_logging() -> Any:
    yield
    core_mod._reset_logging_for_tests()
