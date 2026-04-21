# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Targeted mutation-kill tests for `resilient_exporter.py`.

These tests run under the mutation gate (dev-group only — no `--extra otel`),
so the `_load_failure_result` branches import opentelemetry lazily and raise
`ImportError` when reached. That's enough to distinguish signal-string
mutations (`"logs"` → `"XXlogsXX"`/`"LOGS"` etc.): the original reaches the
import and raises ImportError, the mutant falls through all three branches
and raises `ValueError("unknown signal ...")`.
"""

from __future__ import annotations

from typing import Any

import pytest

from provide.telemetry.resilient_exporter import (
    ResilientExporter,
    _load_failure_result,
)


class _FakeInnerExporter:
    def __init__(self) -> None:
        self.export_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.shutdown_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.flush_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def export(self, *args: Any, **kwargs: Any) -> str:
        self.export_calls.append((args, kwargs))
        return "exported"

    def shutdown(self, *args: Any, **kwargs: Any) -> str:
        self.shutdown_calls.append((args, kwargs))
        return "shutdown"

    def force_flush(self, *args: Any, **kwargs: Any) -> str:
        self.flush_calls.append((args, kwargs))
        return "flushed"


@pytest.mark.parametrize("signal", ["logs", "traces", "metrics"])
def test_load_failure_result_reaches_signal_branch_not_valueerror(signal: str) -> None:
    """Mutants that rename signal literals (`"logs"` → `"LOGS"`, etc.) cause
    the function to skip every branch and fall through to the ValueError at
    the end. Pin: each of the three real signals must NOT raise ValueError —
    it either returns the enum (real OTel present) or raises ImportError
    (dev-only env under mutation gate).
    """
    try:
        result = _load_failure_result(signal)
    except (ImportError, ModuleNotFoundError):
        return  # reached the real import branch; opentelemetry not installed
    except ValueError:
        pytest.fail(f"signal {signal!r} fell through to ValueError — mutant likely renamed the literal")
    # OTel is installed; the real enum came back — mutant signal-literals
    # would have hit ValueError before getting here.
    assert result is not None


def test_export_forwards_kwargs_to_inner_exporter() -> None:
    """Mutant: `lambda: inner_export(*args, )` drops kwargs. Pin: any
    kwargs supplied to the wrapper propagate to the inner exporter.
    """
    inner = _FakeInnerExporter()
    wrapper = ResilientExporter("logs", inner, failure_result="SENTINEL")
    wrapper.export(["batch"], timeout_millis=1234, extra_flag=True)
    assert inner.export_calls == [
        (
            (["batch"],),
            {"timeout_millis": 1234, "extra_flag": True},
        )
    ], "kwargs must survive the run_with_resilience lambda"


def test_shutdown_forwards_both_args_and_kwargs() -> None:
    """Mutants drop either `*args` or `**kwargs` when forwarding to inner.
    Pin: both positional and keyword arguments must reach the inner.
    """
    inner = _FakeInnerExporter()
    wrapper = ResilientExporter("logs", inner, failure_result="SENTINEL")
    wrapper.shutdown("pos", timeout_millis=500)
    assert inner.shutdown_calls == [(("pos",), {"timeout_millis": 500})]


def test_force_flush_forwards_both_args_and_kwargs() -> None:
    """Mutants drop either `*args` or `**kwargs` when forwarding to inner.
    Pin: both positional and keyword arguments must reach the inner.
    """
    inner = _FakeInnerExporter()
    wrapper = ResilientExporter("logs", inner, failure_result="SENTINEL")
    wrapper.force_flush("pos", timeout_millis=999)
    assert inner.flush_calls == [(("pos",), {"timeout_millis": 999})]
