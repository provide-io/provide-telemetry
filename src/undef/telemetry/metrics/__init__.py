# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Metrics facade."""

from undef.telemetry.metrics.api import counter, gauge, histogram
from undef.telemetry.metrics.fallback import Counter, Gauge, Histogram
from undef.telemetry.metrics.provider import get_meter, setup_metrics, shutdown_metrics

__all__ = [
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
