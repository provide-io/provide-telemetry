# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Compatibility layer for metrics helpers."""

from __future__ import annotations

from undef.telemetry.metrics.api import counter, gauge, histogram
from undef.telemetry.metrics.fallback import Counter, Gauge, Histogram

__all__ = ["Counter", "Gauge", "Histogram", "counter", "gauge", "histogram"]
