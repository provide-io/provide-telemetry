# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Observable (callback-reported) instruments.

See prometheus_metrics.observable_instruments in spec/telemetry-api.yaml. A
callback runs at each collection (every scrape for Prometheus, every export
interval for OTLP) and returns the current observations. Like the synchronous
instruments, an observable binds to the provider live at creation: create it
after setup_telemetry(), or its callback never runs.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from provide.telemetry.health import increment_emitted
from provide.telemetry.metrics.provider import _load_otel_metrics_api, get_meter

__all__ = [
    "ObservableInstrument",
    "Observation",
    "observable_counter",
    "observable_gauge",
    "observable_up_down_counter",
]

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Observation:
    """One value an observable instrument's callback reports."""

    value: float
    attributes: Mapping[str, str] | None = None


ObservableCallback = Callable[[], Iterable[Observation]]


class ObservableInstrument:
    """A registered observable; unregister() stops its callback."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._registered = False
        self._failures = 0
        self._lock = threading.Lock()

    @property
    def registered(self) -> bool:
        """Whether the callback is attached to a provider and not unregistered."""
        return self._registered

    def unregister(self) -> None:
        """Stop the callback. Calling it again, or on an unattached instrument, is a no-op."""
        self._registered = False

    def _warn_once(self) -> None:
        with self._lock:
            self._failures += 1
            first = self._failures == 1
        if first:
            _logger.warning("metrics.observable_callback_failed", exc_info=True, extra={"instrument": self.name})


def _metrics_allowed() -> bool:
    """The collection-time metrics gates: the runtime enabled flag and consent."""
    from provide.telemetry._lifecycle import coordinator
    from provide.telemetry.consent import should_allow

    config = coordinator.peek().config
    if config is not None and not config.metrics.enabled:
        return False
    return should_allow("metrics")


def _collector(
    handle: ObservableInstrument, callback: ObservableCallback, make: Callable[[float, dict[str, str]], Any]
) -> Callable[[Any], list[Any]]:
    """The OTel callback: gates, runs callback, converts with make(value, attributes)."""

    def collect(options: Any) -> list[Any]:
        del options  # OTel's CallbackOptions carries only a timeout this collector has no use for
        if not handle.registered or not _metrics_allowed():
            return []
        try:
            observations = [make(float(o.value), dict(o.attributes or {})) for o in callback()]
        except Exception:
            handle._warn_once()
            return []
        for _ in observations:
            increment_emitted("metrics")
        return observations

    return collect


def _register(
    factory: str, name: str, callback: ObservableCallback, description: str | None, unit: str | None
) -> ObservableInstrument:
    handle = ObservableInstrument(name)
    meter = get_meter()
    otel_metrics = _load_otel_metrics_api()
    if meter is None or otel_metrics is None:
        return handle
    try:
        getattr(meter, factory)(
            name,
            callbacks=[_collector(handle, callback, otel_metrics.Observation)],
            description=description or "",
            unit=unit or "",
        )
    except Exception:
        _logger.warning("metrics.observable.create_failed", exc_info=True, extra={"instrument": name})
        return handle
    handle._registered = True
    return handle


def observable_counter(
    name: str, callback: ObservableCallback, description: str | None = None, unit: str | None = None
) -> ObservableInstrument:
    """Register callback as a monotonic counter reporting cumulative totals."""
    return _register("create_observable_counter", name, callback, description, unit)


def observable_gauge(
    name: str, callback: ObservableCallback, description: str | None = None, unit: str | None = None
) -> ObservableInstrument:
    """Register callback as a gauge; a series it stops reporting disappears from the next collection."""
    return _register("create_observable_gauge", name, callback, description, unit)


def observable_up_down_counter(
    name: str, callback: ObservableCallback, description: str | None = None, unit: str | None = None
) -> ObservableInstrument:
    """Register callback as a non-monotonic sum."""
    return _register("create_observable_up_down_counter", name, callback, description, unit)
