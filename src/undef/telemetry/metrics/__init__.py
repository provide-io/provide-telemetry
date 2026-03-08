# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
"""Metrics facade."""

from undef.telemetry.metrics.instruments import Counter, Gauge, Histogram, counter, gauge, histogram
from undef.telemetry.metrics.provider import _HAS_OTEL_METRICS, get_meter, setup_metrics, shutdown_metrics

__all__ = [
    "_HAS_OTEL_METRICS",
    "Counter",
    "Gauge",
    "Histogram",
    "counter",
    "gauge",
    "get_meter",
    "histogram",
    "setup_metrics",
    "shutdown_metrics",
]
