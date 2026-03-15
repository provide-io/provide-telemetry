# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Metric instrument factory functions."""

from __future__ import annotations

import logging

from undef.telemetry.metrics.fallback import Counter, Gauge, Histogram
from undef.telemetry.metrics.provider import get_meter

__all__ = ["counter", "gauge", "histogram"]

_logger = logging.getLogger(__name__)


def counter(name: str, description: str | None = None, unit: str | None = None) -> Counter:
    desc = "" if description is None else description
    metric_unit = "" if unit is None else unit
    meter = get_meter()
    if meter is not None:
        try:
            return Counter(name, meter.create_counter(name=name, description=desc, unit=metric_unit))
        except Exception:
            _logger.warning("failed to create OTel counter %r, falling back to no-op", name, exc_info=True)
            return Counter(name)
    return Counter(name)


def gauge(name: str, description: str | None = None, unit: str | None = None) -> Gauge:
    desc = "" if description is None else description
    metric_unit = "" if unit is None else unit
    meter = get_meter()
    if meter is not None:
        try:
            return Gauge(name, meter.create_up_down_counter(name=name, description=desc, unit=metric_unit))
        except Exception:
            _logger.warning("failed to create OTel gauge %r, falling back to no-op", name, exc_info=True)
            return Gauge(name)
    return Gauge(name)


def histogram(name: str, description: str | None = None, unit: str | None = None) -> Histogram:
    desc = "" if description is None else description
    metric_unit = "" if unit is None else unit
    meter = get_meter()
    if meter is not None:
        try:
            return Histogram(name, meter.create_histogram(name=name, description=desc, unit=metric_unit))
        except Exception:
            _logger.warning("failed to create OTel histogram %r, falling back to no-op", name, exc_info=True)
            return Histogram(name)
    return Histogram(name)
