# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Render collected OTel metrics in the Prometheus text exposition format.

Names go through the reference translation in _prom_names. A scraper that
negotiates escaping=allow-utf-8 (Prometheus 3 does) gets the UTF-8 names of the
NoUTF8/NoTranslation strategies in the quoted text-format syntax; any other
scraper gets the UnderscoreEscaping output with the same suffix choice, as
prometheus_metrics.translation.rules requires.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from provide.telemetry.metrics import _prom_names as names

CONTENT_TYPE_TEXT = "text/plain; version=0.0.4; charset=utf-8; escaping=underscores"
CONTENT_TYPE_UTF8 = "text/plain; version=1.0.0; charset=utf-8; escaping=allow-utf-8"

TARGET_INFO = "target_info"
TARGET_INFO_HELP = "Target metadata"

_LEGACY_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LEGACY_LABEL = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


@dataclass(frozen=True, slots=True)
class RenderOptions:
    strategy: str
    scope_labels: bool = False
    target_info: bool = True
    utf8: bool = False  # the scraper negotiated escaping=allow-utf-8


@dataclass(slots=True)
class Family:
    """One metric family: a translated name, a Prometheus type and its samples."""

    name: str
    kind: str  # counter | gauge | histogram
    help: str = ""
    samples: list[tuple[str, dict[str, str], float]] = field(default_factory=list)  # (suffix, labels, value)


def wants_utf8(accept: str | None) -> bool:
    """Whether an Accept header asks for the text format with UTF-8 names."""
    if not accept:
        return False
    for media_range in accept.split(","):
        params = [p.strip().lower() for p in media_range.split(";")]
        if params[0] == "text/plain" and "escaping=allow-utf-8" in params[1:]:
            return True
    return False


def effective_strategy(opts: RenderOptions) -> str:
    """The strategy to translate with for this scrape."""
    if names.escapes(opts.strategy) or opts.utf8:
        return opts.strategy
    return (
        "UnderscoreEscapingWithSuffixes" if names.adds_suffixes(opts.strategy) else "UnderscoreEscapingWithoutSuffixes"
    )


def _kind_of(data: Any) -> tuple[str, str] | None:
    """(translation kind, Prometheus type) for an OTel data object, or None if unsupported."""
    kind = type(data).__name__
    if kind == "Sum":
        if data.is_monotonic:
            return names.KIND_MONOTONIC_COUNTER, "counter"
        return names.KIND_NON_MONOTONIC_COUNTER, "gauge"
    if kind == "Gauge":
        return names.KIND_GAUGE, "gauge"
    if kind == "Histogram":
        return names.KIND_HISTOGRAM, "histogram"
    return None  # exponential histograms are not exported over this path


def translate_labels(attributes: Mapping[str, Any], strategy: str) -> dict[str, str]:
    """Translate attribute keys to label names, dropping keys that cannot be labels.

    A key the reference rejects, or translates to a name starting with "__"
    (reserved by Prometheus), is dropped; the sample is kept.
    """
    labels: dict[str, str] = {}
    for key, value in attributes.items():
        try:
            label = names.label_name(str(key), strategy)
        except ValueError:
            continue
        if not label.startswith("__"):
            labels[label] = str(value)
    return labels


def families_from(metrics_data: Any, opts: RenderOptions) -> list[Family]:
    """Convert an OTel MetricsData into families keyed by translated name."""
    strategy = effective_strategy(opts)
    families: dict[str, Family] = {}
    info = Family(TARGET_INFO, "gauge", TARGET_INFO_HELP)
    for resource_metrics in getattr(metrics_data, "resource_metrics", None) or ():
        resource_labels = translate_labels(resource_metrics.resource.attributes, strategy)
        if opts.target_info and resource_labels:
            info.samples.append(("", resource_labels, 1.0))
        for scope_metrics in resource_metrics.scope_metrics:
            scope = _scope_labels(scope_metrics.scope) if opts.scope_labels else {}
            for metric in scope_metrics.metrics:
                _add_metric(families, metric, scope, strategy)
    if info.samples:
        families.setdefault(TARGET_INFO, info)
    return sorted(families.values(), key=lambda f: f.name)


def _scope_labels(scope: Any) -> dict[str, str]:
    labels = {"otel_scope_name": scope.name}
    if scope.version:
        labels["otel_scope_version"] = scope.version
    return labels


def _add_metric(families: dict[str, Family], metric: Any, scope: dict[str, str], strategy: str) -> None:
    kinds = _kind_of(metric.data)
    if kinds is None:
        return
    kind, prom_type = kinds
    try:
        name = names.metric_name(metric.name, metric.unit or "", kind, strategy)
    except ValueError:
        return
    family = families.setdefault(name, Family(name, prom_type, metric.description or ""))
    if family.kind != prom_type:
        return  # a second instrument under the same translated name but another type
    for point in metric.data.data_points:
        labels = {**translate_labels(point.attributes, strategy), **scope}
        if prom_type == "histogram":
            family.samples.extend(_histogram_samples(point, labels))
        else:
            family.samples.append(("", labels, float(point.value)))


def _histogram_samples(point: Any, labels: dict[str, str]) -> Iterable[tuple[str, dict[str, str], float]]:
    running = 0
    for index, bound in enumerate(point.explicit_bounds):
        running += point.bucket_counts[index]
        yield "_bucket", {**labels, "le": format_value(bound)}, float(running)
    yield "_bucket", {**labels, "le": "+Inf"}, float(point.count)
    yield "_sum", labels, float(point.sum)
    yield "_count", labels, float(point.count)


def format_value(value: float) -> str:
    """Format a sample value: the shortest repr, without a trailing ".0"."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return f"{value:+}".replace("inf", "Inf")
    return repr(float(value)).removesuffix(".0")


def _escape_help(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def _escape_quoted(text: str) -> str:
    """Escape a label value or a quoted name: backslash, newline and double quote."""
    return _escape_help(text).replace('"', '\\"')


def _label_pairs(labels: Mapping[str, str]) -> list[str]:
    pairs = []
    for key, value in labels.items():
        name = key if _LEGACY_LABEL.match(key) else f'"{_escape_quoted(key)}"'
        pairs.append(f'{name}="{_escape_quoted(value)}"')
    return pairs


def _sample_line(name: str, labels: Mapping[str, str], value: float) -> str:
    pairs = _label_pairs(labels)
    if _LEGACY_NAME.match(name):
        return f"{name}{{{','.join(pairs)}}} {format_value(value)}" if pairs else f"{name} {format_value(value)}"
    return f'{{"{_escape_quoted(name)}"{"".join("," + p for p in pairs)}}} {format_value(value)}'


def render(families: Iterable[Family]) -> str:
    """Render families as text exposition, HELP and TYPE first in each."""
    lines: list[str] = []
    for family in families:
        header = family.name if _LEGACY_NAME.match(family.name) else f'"{_escape_quoted(family.name)}"'
        if family.help:
            lines.append(f"# HELP {header} {_escape_help(family.help)}")
        lines.append(f"# TYPE {header} {family.kind}")
        lines.extend(_sample_line(family.name + suffix, labels, value) for suffix, labels, value in family.samples)
    return "\n".join(lines) + "\n" if lines else ""
