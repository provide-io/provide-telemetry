# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""PROVIDE_METRICS_HEALTH_OTLP: the health series as observable instruments.

See prometheus_metrics.health_metrics in spec/telemetry-api.yaml. Each health
family becomes one observable instrument, named verbatim, on the provider setup
installs, so the series are exported over OTLP too. The observations describe
the SDK rather than user data: they are not consent-gated and do not count
toward emitted_metrics. The pull renderer skips these instruments, so a scrape
carries only the collector's copy.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from provide.telemetry.metrics import prometheus

_FACTORIES = {"counter": "create_observable_counter", "gauge": "create_observable_gauge"}


def _current() -> list[Any]:
    from provide.telemetry.health import get_health_snapshot

    return prometheus.health_families(get_health_snapshot())


def _collector(name: str, make: Callable[[float, dict[str, str]], Any]) -> Callable[[Any], list[Any]]:
    def collect(options: Any) -> list[Any]:
        del options  # OTel's CallbackOptions carries only a timeout this collector has no use for
        family = next(f for f in _current() if f.name == name)
        return [make(value, labels) for _, labels, value in family.samples]

    return collect


def register(meter: Any, make: Callable[[float, dict[str, str]], Any]) -> None:
    """Create one observable per health family on meter; make builds an OTel Observation."""
    for family in _current():
        getattr(meter, _FACTORIES[family.kind])(family.name, callbacks=[_collector(family.name, make)])
