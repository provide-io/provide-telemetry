# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Immutable public value types used by the runtime facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from provide.telemetry.config import TelemetryConfig

# Per-signal drain outcome, as reported by ``setup.flush_signals``. Three-valued
# because a caller alerting on export loss treats the cases differently: a
# ``timed_out`` drain may still complete in the background, a ``failed`` one
# raised and will not. Matches Go's facade (DeadlineExceeded → TimedOut, any
# other error → Failed).
SignalDrainOutcome = Literal["flushed", "timed_out", "failed"]


class ProviderMode(StrEnum):
    """How the runtime owns providers."""

    OWNED = "owned"
    HOST = "host"
    LOCAL = "local"


class RuntimeState(StrEnum):
    """Lifecycle state for the active runtime."""

    LOCAL = "local"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    RECONFIGURING = "reconfiguring"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass(frozen=True)
class SignalFlushResult:
    flushed: bool = False
    not_installed: bool = False
    not_owned: bool = False
    timed_out: bool = False
    failed: bool = False


@dataclass(frozen=True)
class FlushResult:
    """Per-signal outcome of a facade flush.

    Truthiness preserves the pre-0.7 ``flush() -> bool`` contract, so
    ``if not telemetry.flush(): alert()`` keeps meaning what it did: ``True``
    iff no signal timed out or failed. A signal with nothing of ours to drain
    (``not_installed`` / ``not_owned``) counts as success, exactly as
    ``flush_telemetry()`` reports it.
    """

    logs: SignalFlushResult = field(default_factory=SignalFlushResult)
    traces: SignalFlushResult = field(default_factory=SignalFlushResult)
    metrics: SignalFlushResult = field(default_factory=SignalFlushResult)

    def __bool__(self) -> bool:
        return not any(s.timed_out or s.failed for s in (self.logs, self.traces, self.metrics))


@dataclass(frozen=True)
class ReconfigureResult:
    """Outcome of an attempted runtime reconfiguration.

    Field names are the cross-language canonical set — ``previous``/``current``
    name the configs on either side of the attempt, and ``state`` is the runtime
    state after it. Go, Rust and TypeScript declare the same five fields under the
    same names so a result serialized by one runtime deserializes in another.
    """

    applied: bool
    current: TelemetryConfig | None = None
    previous: TelemetryConfig | None = None
    state: RuntimeState = RuntimeState.READY
    error: str | None = None


@dataclass(frozen=True)
class RuntimeStatus:
    setup_done: bool
    signals: dict[str, bool]
    providers: dict[str, bool]
    fallback: dict[str, bool]
    setup_error: str | None
