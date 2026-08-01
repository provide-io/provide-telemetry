# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Immutable public value types used by the runtime facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from provide.telemetry.config import TelemetryConfig


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
    logs: SignalFlushResult = field(default_factory=SignalFlushResult)
    traces: SignalFlushResult = field(default_factory=SignalFlushResult)
    metrics: SignalFlushResult = field(default_factory=SignalFlushResult)


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
