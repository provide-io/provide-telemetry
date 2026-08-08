# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Immutable lifecycle generations and the one lock that publishes them.

Setup and the runtime API used to own separate locks over separate halves of
the same state — ``setup._setup_done`` under one, ``runtime._active_config``
under another — so "how is telemetry configured right now" had no single
answer and no single owner. A reconfiguration published its config before it
had finished applying the policies that config describes, and a repeated
``setup_telemetry()`` parsed the caller's new input before discovering it was
going to ignore it.

A :class:`LifecycleGeneration` is the whole answer to that question: a
generation number, the config, and whether setup completed. It is built
complete and published once, exactly as Go's ``runtimeGeneration`` is
(``go/runtime_generation.go``) — a reader sees the previous world or the next
one, never a half-applied mix.
"""

from __future__ import annotations

__all__ = [
    "LifecycleCoordinator",
    "LifecycleGeneration",
    "coordinator",
    "copy_config",
]

import copy
import threading
from dataclasses import dataclass

from provide.telemetry.config import TelemetryConfig


@dataclass(frozen=True, slots=True)
class LifecycleGeneration:
    """One complete, immutable view of the telemetry lifecycle.

    *config* is ``None`` for generation 0 and after a teardown: no config has
    been applied, and callers fall back to :meth:`TelemetryConfig.from_env`
    rather than to dataclass defaults, so a process that only ever set
    ``PROVIDE_*`` environment variables still reports what it is running.
    """

    number: int
    config: TelemetryConfig | None
    setup_done: bool


_INITIAL = LifecycleGeneration(0, None, False)


class LifecycleCoordinator:
    """Serializes lifecycle operations and publishes their result atomically.

    Two locks, because they answer two different questions.

    ``operations`` serializes whole lifecycle *operations* — setup, update,
    reconfigure, shutdown — against each other. It is re-entrant so a
    reconfiguration that has to tear down and set back up does not deadlock on
    itself.

    ``_condition`` guards the generation *bump*, and only the bump. Readers do
    not take it: a generation is frozen and published by a single reference
    assignment, which the GIL makes atomic, so a reader gets one complete
    generation or another and never has to wait for a slow reconfiguration to
    finish. This is the same trade Go makes with ``atomic.Pointer``.
    """

    __slots__ = ("_condition", "_generation", "_operations")

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._operations = threading.RLock()
        self._generation = _INITIAL

    @property
    def operations(self) -> threading.RLock:
        """The lock that serializes lifecycle operations against each other."""
        return self._operations

    def peek(self) -> LifecycleGeneration:
        """Return the live generation, without a lock and without copying.

        This is the read every log record makes, so it is one attribute load.
        Safe because the record is frozen and its config is never mutated after
        publication; a caller that hands the config to user code wants
        :meth:`snapshot`.
        """
        return self._generation

    def snapshot(self) -> LifecycleGeneration:
        """Return the live generation with a defensive copy of its config."""
        generation = self._generation
        config = generation.config
        return LifecycleGeneration(
            generation.number,
            None if config is None else copy_config(config),
            generation.setup_done,
        )

    def publish(self, config: TelemetryConfig | None, *, setup_done: bool) -> LifecycleGeneration:
        """Replace the live generation with a complete new one.

        The whole bump — read, increment, store, notify — happens under
        ``_condition``. ``notify_all()`` raises ``RuntimeError`` when the
        condition's lock is not held, and the same hold is what stops two
        concurrent publications from landing on the same generation number.
        """
        with self._condition:
            self._generation = LifecycleGeneration(
                self._generation.number + 1,
                None if config is None else copy_config(config),
                setup_done,
            )
            self._condition.notify_all()
            return self.snapshot()

    def publish_setup_state(self, *, setup_done: bool) -> LifecycleGeneration:
        """Republish the live config under a new setup latch."""
        with self._condition:
            return self.publish(self._generation.config, setup_done=setup_done)

    def wait_for_generation(self, after: int, timeout: float) -> LifecycleGeneration | None:
        """Block until a generation later than *after* is published.

        Returns the new generation, or ``None`` if *timeout* elapsed first.
        This is what :meth:`publish`'s ``notify_all()`` is for: a caller that
        has to observe the *next* complete world — a test asserting that a
        reconfiguration published nothing until its policies finished, or a
        supervisor waiting for a hot reload to land — would otherwise have to
        poll and could sample a generation that had not been published yet.
        """
        with self._condition:
            published = self._condition.wait_for(lambda: self._generation.number > after, timeout)
            if not published:
                return None
            return self.snapshot()

    def reset(self) -> None:
        """Drop back to the pre-setup generation. Test and teardown support."""
        with self._condition:
            self._generation = _INITIAL
            self._condition.notify_all()


def copy_config(config: TelemetryConfig) -> TelemetryConfig:
    """Deep-copy config data while carrying ``receipt_sink`` by reference.

    Seeding the memo with the caller's sink is what keeps it out of the copy. A
    bare ``copy.deepcopy(config)`` clones it, so ``emit_receipt`` would deliver
    every governance receipt to a duplicate the caller never reads — and a sink
    holding a socket, a file handle or a database client would raise
    ``TypeError`` from the copy rather than copying at all.
    """
    sink = config.receipt_sink
    memo: dict[int, object] = {} if sink is None else {id(sink): sink}
    return copy.deepcopy(config, memo)


coordinator = LifecycleCoordinator()
