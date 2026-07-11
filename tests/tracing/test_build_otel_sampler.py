# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cover build_otel_trace_sampler without the otel extra (quality CI)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from provide.telemetry import _otel


def test_build_otel_trace_sampler_parent_based_with_mock_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Success path must run under no-otel quality (covers _otel.py clamp + ParentBased)."""

    class _TraceIdRatioBased:
        def __init__(self, rate: float) -> None:
            self.rate = rate

    class _ParentBased:
        def __init__(self, root: object) -> None:
            self.root = root

    fake_sampling = SimpleNamespace(TraceIdRatioBased=_TraceIdRatioBased, ParentBased=_ParentBased)

    def _import(name: str) -> object:
        if name == "opentelemetry.sdk.trace.sampling":
            return fake_sampling
        raise ImportError(name)

    monkeypatch.setattr(_otel, "_import_module", _import)
    sampler = _otel.build_otel_trace_sampler(0.25)
    assert isinstance(sampler, _ParentBased)
    assert isinstance(sampler.root, _TraceIdRatioBased)
    assert sampler.root.rate == 0.25


def test_build_otel_trace_sampler_clamps_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TraceIdRatioBased:
        def __init__(self, rate: float) -> None:
            self.rate = rate

    class _ParentBased:
        def __init__(self, root: object) -> None:
            self.root = root

    fake_sampling = SimpleNamespace(TraceIdRatioBased=_TraceIdRatioBased, ParentBased=_ParentBased)
    monkeypatch.setattr(
        _otel,
        "_import_module",
        lambda name: fake_sampling if name.endswith(".sampling") else (_ for _ in ()).throw(ImportError(name)),
    )
    high = _otel.build_otel_trace_sampler(2.0)
    low = _otel.build_otel_trace_sampler(-1.0)
    assert high is not None and high.root.rate == 1.0
    assert low is not None and low.root.rate == 0.0


def test_build_otel_trace_sampler_returns_none_without_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_otel, "_import_module", lambda _name: (_ for _ in ()).throw(ImportError("no sdk")))
    assert _otel.build_otel_trace_sampler(0.5) is None
