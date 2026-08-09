# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Deterministic interleavings across the lifecycle coordinator.

Each test pins a window that used to be observable: a generation published
before its policies were installed, a repeated setup that parsed input it was
never going to apply, a status read that queued behind a stalled teardown, and
a receipt sink cloned out from under its owner.
"""

from __future__ import annotations

import threading

import pytest

from provide.telemetry import runtime as runtime_mod
from provide.telemetry import setup as setup_mod
from provide.telemetry._lifecycle import LifecycleCoordinator, LifecycleGeneration
from provide.telemetry.config import LoggingConfig, RuntimeOverrides, TelemetryConfig
from provide.telemetry.receipts import TestReceiptCollector
from provide.telemetry.runtime import (
    get_runtime_config,
    get_runtime_status,
    reconfigure_telemetry,
    update_runtime_config,
)
from provide.telemetry.setup import _reset_all_for_tests, setup_telemetry, shutdown_telemetry

_WAIT = 5.0


@pytest.fixture(autouse=True)
def _clean_lifecycle() -> None:
    _reset_all_for_tests()


def test_repeated_setup_returns_the_active_config_without_parsing_new_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second setup_telemetry() must not read input it has already decided to ignore.

    Parsing first meant a repeated call raised ConfigurationError over an
    environment the running process was never going to adopt.
    """
    active = setup_telemetry(TelemetryConfig(service_name="active"))
    monkeypatch.setenv("PROVIDE_TRACE_SAMPLE_RATE", "not-a-number")

    repeated = setup_telemetry()

    assert repeated == active
    assert repeated is not active
    assert repeated.service_name == "active"


def test_repeated_setup_ignores_a_config_argument_too() -> None:
    active = setup_telemetry(TelemetryConfig(service_name="active"))
    repeated = setup_telemetry(TelemetryConfig(service_name="ignored"))
    assert repeated.service_name == "active"
    assert active.service_name == "active"


def test_update_publishes_nothing_until_its_policies_are_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The generation appears only once the policies it describes are in force."""
    runtime_mod.apply_runtime_config(TelemetryConfig(service_name="svc", pii_max_depth=4))
    entered = threading.Event()
    release = threading.Event()

    def _blocked(snapshot: TelemetryConfig) -> None:
        entered.set()
        assert release.wait(_WAIT)

    monkeypatch.setattr(runtime_mod, "apply_policies", _blocked)
    worker = threading.Thread(target=lambda: update_runtime_config(RuntimeOverrides(pii_max_depth=7)), daemon=True)
    worker.start()
    try:
        assert entered.wait(_WAIT)
        # Mid-application: the previous generation is still the published one.
        assert get_runtime_config().pii_max_depth == 4
    finally:
        release.set()
    worker.join(_WAIT)
    assert not worker.is_alive()
    assert get_runtime_config().pii_max_depth == 7


def test_setup_and_reconfigure_hand_back_the_callers_own_receipt_sink() -> None:
    """The sink is carried by reference through every lifecycle copy.

    A plain deepcopy of the config clones it, so receipts would be delivered to
    a duplicate the caller never reads — or the copy would raise outright for a
    sink holding a socket or a database client.
    """
    sink = TestReceiptCollector()
    active = setup_telemetry(TelemetryConfig(service_name="active", receipt_sink=sink))
    assert active.receipt_sink is sink
    assert get_runtime_config().receipt_sink is sink

    reconfigured = reconfigure_telemetry(
        TelemetryConfig(service_name="active", logging=LoggingConfig(level="DEBUG"), receipt_sink=None)
    )

    assert reconfigured.receipt_sink is sink
    assert reconfigured.logging.level == "DEBUG"


def test_a_config_carrying_a_sink_that_cannot_be_copied_still_publishes() -> None:
    class _Uncopyable:
        def __deepcopy__(self, memo: dict[int, object]) -> object:
            raise TypeError("a sink holding a socket cannot be copied")

        def emit(self, receipt: object, /) -> bool:
            return True

    sink = _Uncopyable()
    published = setup_telemetry(TelemetryConfig(service_name="svc", receipt_sink=sink))
    assert published.receipt_sink is sink
    assert get_runtime_config().receipt_sink is sink


def test_runtime_status_answers_while_a_provider_teardown_is_stalled() -> None:
    """Status is what an operator calls *during* a hanging shutdown.

    It must not queue behind the drain it is being used to observe, so each
    per-signal teardown detaches its provider before draining it and the setup
    latch is published ahead of the disposal.
    """
    from provide.telemetry.tracing import provider as tracing_provider

    entered = threading.Event()
    release = threading.Event()

    class _StalledProvider:
        def force_flush(self) -> bool:
            return True

        def shutdown(self) -> None:
            entered.set()
            assert release.wait(_WAIT)

    setup_telemetry(TelemetryConfig(service_name="svc"))
    tracing_provider._provider_ref = _StalledProvider()
    tracing_provider._provider_configured = True

    worker = threading.Thread(target=lambda: shutdown_telemetry(timeout_seconds=_WAIT), daemon=True)
    worker.start()
    try:
        assert entered.wait(_WAIT)
        status = get_runtime_status()
        assert status.setup_done is False
        assert status.providers["traces"] is False
    finally:
        release.set()
    worker.join(_WAIT)
    assert not worker.is_alive()


# ── LifecycleCoordinator unit behaviour ─────────────────────────────────────


def test_publish_bumps_the_number_and_returns_a_copy() -> None:
    coordinator = LifecycleCoordinator()
    assert coordinator.peek() == LifecycleGeneration(0, None, False)

    config = TelemetryConfig(service_name="one")
    published = coordinator.publish(config, setup_done=True)

    assert published.number == 1
    assert published.setup_done is True
    assert published.config == config
    assert published.config is not config
    assert coordinator.peek().config is not published.config


def test_snapshot_of_an_unpublished_coordinator_has_no_config() -> None:
    coordinator = LifecycleCoordinator()
    assert coordinator.snapshot().config is None


def test_reset_returns_to_the_pre_setup_generation() -> None:
    coordinator = LifecycleCoordinator()
    coordinator.publish(TelemetryConfig(), setup_done=True)
    coordinator.reset()
    assert coordinator.peek() == LifecycleGeneration(0, None, False)


def test_wait_for_generation_wakes_on_publication() -> None:
    """publish() notifies under the condition it holds — an unheld lock raises."""
    coordinator = LifecycleCoordinator()
    seen: list[LifecycleGeneration | None] = []
    ready = threading.Event()

    def _watch() -> None:
        ready.set()
        seen.append(coordinator.wait_for_generation(after=0, timeout=_WAIT))

    watcher = threading.Thread(target=_watch, daemon=True)
    watcher.start()
    assert ready.wait(_WAIT)
    coordinator.publish(TelemetryConfig(service_name="published"), setup_done=False)
    watcher.join(_WAIT)

    assert seen[0] is not None
    assert seen[0].number == 1
    assert seen[0].config is not None
    assert seen[0].config.service_name == "published"


def test_wait_for_generation_gives_up_at_its_timeout() -> None:
    """Waited from a worker, because the failure being pinned is "never returns".

    ``timeout`` is the whole promise of this call — a supervisor waiting on a
    hot reload that never lands has to get control back — so a dropped or
    ``None`` timeout is not a wrong answer but a hang, and asserting it from the
    test's own thread would hang the suite rather than fail it. The worker is
    released afterwards so nothing is left blocked on the coordinator.
    """
    coordinator = LifecycleCoordinator()
    seen: list[LifecycleGeneration | None] = []
    waiter = threading.Thread(target=lambda: seen.append(coordinator.wait_for_generation(after=0, timeout=0.01)))
    waiter.daemon = True
    waiter.start()
    waiter.join(_WAIT)
    returned = not waiter.is_alive()
    if not returned:
        # Publishing is the only thing that wakes a wait with no deadline.
        coordinator.publish(TelemetryConfig(), setup_done=False)
        waiter.join(_WAIT)

    assert returned, "wait_for_generation ignored its timeout and blocked"
    assert seen == [None]


def test_a_fresh_coordinator_serializes_operations_re_entrantly() -> None:
    """``operations`` is a real re-entrant lock from the first construction.

    Re-entrant because a reconfiguration that has to tear down and set back up
    takes it again from inside itself; a plain Lock deadlocks there. And it has
    to serialize: a second thread must not enter while the first holds it, which
    is what stops a shutdown from tearing down providers a concurrent setup just
    installed.
    """
    coordinator = LifecycleCoordinator()
    entered_while_held = threading.Event()

    def _contend() -> None:
        with coordinator.operations:
            entered_while_held.set()

    with coordinator.operations:
        assert coordinator.operations.acquire(timeout=_WAIT), "operations is not re-entrant"
        coordinator.operations.release()

        contender = threading.Thread(target=_contend, daemon=True)
        contender.start()
        assert not entered_while_held.wait(0.05), "operations did not exclude a second thread"

    contender.join(_WAIT)
    assert entered_while_held.is_set()


def test_one_lock_serializes_setup_against_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setup and shutdown are the same operation on the same state.

    Two independent locks let them interleave, which is how a shutdown could
    tear down providers a concurrent setup had just installed.
    """
    setup_telemetry(TelemetryConfig(service_name="svc"))
    entered = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def _blocked_teardown(timeout_seconds: float | None = None) -> None:
        order.append("shutdown")
        entered.set()
        assert release.wait(_WAIT)

    monkeypatch.setattr(setup_mod, "shutdown_logging", _blocked_teardown)
    monkeypatch.setattr("provide.telemetry.setup.configure_logging", lambda _cfg, **_kw: order.append("setup"))

    shutdown_worker = threading.Thread(target=shutdown_telemetry, daemon=True)
    shutdown_worker.start()
    assert entered.wait(_WAIT)
    setup_worker = threading.Thread(target=lambda: setup_telemetry(TelemetryConfig()), daemon=True)
    setup_worker.start()
    # The setup thread is parked on the lifecycle lock, not running ahead of us.
    setup_worker.join(0.05)
    assert setup_worker.is_alive()
    assert order == ["shutdown"]

    release.set()
    shutdown_worker.join(_WAIT)
    setup_worker.join(_WAIT)
    assert order == ["shutdown", "setup"]
