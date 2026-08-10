# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""A drain that raises must not abort shutdown's local cleanup.

``run_drains_together`` re-raises the first drain error. Before the fix, that
skipped every ``_reset_*`` in ``shutdown_telemetry`` and left
``TelemetryRuntime.shutdown`` short of the STOPPED its docstring promises. The
contract now: cleanup always completes, the terminal state is always STOPPED,
and the first drain error still reaches the caller afterwards.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from provide.telemetry import setup as setup_mod
from provide.telemetry._lifecycle import coordinator
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.runtime import RuntimeState, TelemetryRuntime, apply_runtime_config
from provide.telemetry.tracing import provider as tracing_provider


class _ExplodingProvider:
    """A provider whose drain raises promptly — bad auth header, TLS failure."""

    def force_flush(self) -> None:
        raise RuntimeError("exporter exploded")


def _install_exploding_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing_provider, "_provider_ref", _ExplodingProvider())


def test_resets_all_run_and_the_error_still_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every reset runs even though the tracing drain raised, then the error propagates."""
    import provide.telemetry.backpressure as backpressure_mod
    import provide.telemetry.resilience as resilience_mod
    import provide.telemetry.runtime as runtime_mod
    import provide.telemetry.sampling as sampling_mod

    calls: list[str] = []

    def _recorded(name: str, original: Callable[[], None]) -> Callable[[], None]:
        def _run() -> None:
            calls.append(name)
            original()

        return _run

    for module, name in (
        (runtime_mod, "reset_runtime_for_tests"),
        (sampling_mod, "reset_sampling_for_tests"),
        (backpressure_mod, "reset_queues_for_tests"),
        (resilience_mod, "reset_resilience_for_tests"),
    ):
        monkeypatch.setattr(module, name, _recorded(name, getattr(module, name)))

    apply_runtime_config(TelemetryConfig(service_name="doomed-svc"))
    assert coordinator.peek().config is not None
    _install_exploding_tracer(monkeypatch)

    with pytest.raises(RuntimeError, match="exporter exploded"):
        setup_mod.shutdown_telemetry(timeout_seconds=1.0)

    assert calls == [
        "reset_runtime_for_tests",
        "reset_sampling_for_tests",
        "reset_queues_for_tests",
        "reset_resilience_for_tests",
    ]


def test_a_fresh_generation_is_published_despite_the_drain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The active config generation is cleared, not left as the torn-down world's."""
    apply_runtime_config(TelemetryConfig(service_name="doomed-svc"))
    coordinator.publish_setup_state(setup_done=True)
    _install_exploding_tracer(monkeypatch)

    with pytest.raises(RuntimeError, match="exporter exploded"):
        setup_mod.shutdown_telemetry(timeout_seconds=1.0)

    assert coordinator.peek().config is None
    assert coordinator.peek().setup_done is False


def test_runtime_shutdown_reaches_stopped_when_a_drain_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The facade's docstring promises terminal STOPPED either way — make it true."""
    runtime = TelemetryRuntime()
    _install_exploding_tracer(monkeypatch)

    with pytest.raises(RuntimeError, match="exporter exploded"):
        runtime.shutdown(1.0)

    assert runtime._state is RuntimeState.STOPPED
