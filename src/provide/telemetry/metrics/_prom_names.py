# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Prometheus metric and label name translation.

A port of github.com/prometheus/otlptranslator v1.0.0 (MetricNamer and
LabelNamer, without namespaces), the reference named by
prometheus_metrics.translation in spec/telemetry-api.yaml. The cases in
spec/prometheus_fixtures.yaml were generated from that library, so this module
must reproduce it exactly rather than approximate it.
"""

from __future__ import annotations

import re

KIND_MONOTONIC_COUNTER = "monotonic_counter"
KIND_NON_MONOTONIC_COUNTER = "non_monotonic_counter"
KIND_GAUGE = "gauge"
KIND_HISTOGRAM = "histogram"

_UNIT_MAP = {
    "d": "days",
    "h": "hours",
    "min": "minutes",
    "s": "seconds",
    "ms": "milliseconds",
    "us": "microseconds",
    "ns": "nanoseconds",
    "By": "bytes",
    "KiBy": "kibibytes",
    "MiBy": "mebibytes",
    "GiBy": "gibibytes",
    "TiBy": "tibibytes",
    "KBy": "kilobytes",
    "MBy": "megabytes",
    "GBy": "gigabytes",
    "TBy": "terabytes",
    "m": "meters",
    "V": "volts",
    "A": "amperes",
    "J": "joules",
    "W": "watts",
    "g": "grams",
    "Cel": "celsius",
    "Hz": "hertz",
    "1": "",
    "%": "percent",
}
_PER_UNIT_MAP = {"s": "second", "m": "minute", "h": "hour", "d": "day", "w": "week", "mo": "month", "y": "year"}


def escapes(strategy: str) -> bool:
    """Whether the strategy escapes names to the legacy character set."""
    return strategy.startswith("UnderscoreEscaping")


def adds_suffixes(strategy: str) -> bool:
    """Whether the strategy appends unit, _total and _ratio suffixes."""
    return strategy.endswith("WithSuffixes")


_METRIC_SEPARATORS = re.compile(r"[^a-zA-Z0-9:]+")
_METRIC_SEPARATORS_KEEPING_UNDERSCORE = re.compile(r"[^a-zA-Z0-9:_]+")
# Runs of characters outside the legacy sets, "_" included, so replacing each
# run with one "_" also collapses repeated underscores as the reference does.
_INVALID_UNIT_RUNS = re.compile(r"[^a-zA-Z0-9:]+")
_INVALID_LABEL_RUNS = re.compile(r"[^a-zA-Z0-9]+")


def _tokens(separators: re.Pattern[str], name: str) -> list[str]:
    """Split name on separators, dropping empty fields (Go's strings.FieldsFunc)."""
    return [t for t in separators.split(name) if t]


def _clean_up_unit(unit: str) -> str:
    return _INVALID_UNIT_RUNS.sub("_", unit).removeprefix("_")


def _unit_suffix(unit: str) -> str:
    """A unit mapped to its Prometheus spelling, or "" when blank or an {annotation}."""
    unit = unit.strip()
    if not unit or "{" in unit or "}" in unit:
        return ""
    return unit


def _unit_suffixes(unit: str) -> tuple[str, str]:
    """The main and per-unit suffixes for unit, e.g. ("bytes", "per_second") for By/s."""
    main_otel, _, per_otel = unit.partition("/")
    main = _unit_suffix(main_otel)
    per = _unit_suffix(per_otel)
    return _UNIT_MAP.get(main, main), "per_" + _PER_UNIT_MAP.get(per, per) if per else ""


def _add_unit_tokens(tokens: list[str], main: str, per: str) -> list[str]:
    if main in tokens:
        main = ""
    # The reference also drops a per suffix already among the tokens, but that
    # cannot happen: tokens never contain "_" and a per suffix always does.
    per = "" if per == "per_" else per.removesuffix("_")
    if per:
        main = main.removesuffix("_")
    return tokens + [t for t in (main, per) if t]


def _prefix_leading_digit(name: str) -> str:
    return "_" + name if name[:1].isdigit() else name


def _normalize(name: str, unit: str, kind: str) -> str:
    """Full escaping normalization with suffixes (otlptranslator normalizeName)."""
    main, per = _unit_suffixes(unit)
    tokens = _add_unit_tokens(_tokens(_METRIC_SEPARATORS, name), _clean_up_unit(main), _clean_up_unit(per))
    if kind == KIND_MONOTONIC_COUNTER:
        tokens = [t for t in tokens if t != "total"] + ["total"]
    if unit == "1" and kind == KIND_GAUGE:
        tokens = [t for t in tokens if t != "ratio"] + ["ratio"]
    return _prefix_leading_digit("_".join(tokens))


def _trim_suffix(name: str, suffix: str) -> str:
    """Trim suffix plus one delimiter character, when something is left before it."""
    keep = len(name) - len(suffix) - 1
    return name[:keep] if name.endswith(suffix) and keep > 0 else name


def _utf8_with_suffixes(name: str, unit: str, kind: str) -> str:
    """UTF-8 naming with suffixes (otlptranslator buildMetricName).

    Outer suffixes are trimmed first and re-appended last, so the result reads
    name, main unit, per unit, then _total or _ratio.
    """
    outer = ""
    if unit == "1" and kind == KIND_GAUGE:
        name, outer = _trim_suffix(name, "ratio"), "_ratio"
    if kind == KIND_MONOTONIC_COUNTER:
        name, outer = _trim_suffix(name, "total"), "_total"
    main, per = _unit_suffixes(unit)
    per_suffix = ""
    if per:
        name, per_suffix = _trim_suffix(name, per), "_" + per
    if main and not name.endswith(main):
        name = name + "_" + main
    return name + per_suffix + outer


def metric_name(name: str, unit: str, kind: str, strategy: str) -> str:
    """Translate an OTel instrument name into a Prometheus metric name.

    Raises ValueError when translation leaves no usable name, as the reference does.
    """
    if not escapes(strategy):
        return _utf8_with_suffixes(name, unit, kind) if adds_suffixes(strategy) else name
    if adds_suffixes(strategy):
        result = _normalize(name, unit, kind)
    else:
        result = _prefix_leading_digit("_".join(_tokens(_METRIC_SEPARATORS_KEEPING_UNDERSCORE, name)))
    if not result or (result != name and not result.strip("_")):
        raise ValueError(f"metric name {name!r} translates to nothing usable")
    return result


def label_name(attribute: str, strategy: str) -> str:
    """Translate an attribute key into a Prometheus label name.

    Raises ValueError for an empty key or one that is only underscores.
    """
    if not attribute.strip("_"):
        raise ValueError(f"attribute {attribute!r} cannot be a label name")
    if not escapes(strategy):
        return attribute
    # A key that starts and ends with "__" keeps both; shorter such keys are all
    # underscores and were rejected above.
    reserved = attribute.startswith("__") and attribute.endswith("__")
    body = attribute[2:-2] if reserved else attribute
    sanitized = _INVALID_LABEL_RUNS.sub("_", body)
    if reserved:
        sanitized = "__" + sanitized + "__"
    if sanitized[:1].isdigit():
        sanitized = "key_" + sanitized
    if not sanitized.strip("_"):
        raise ValueError(f"attribute {attribute!r} cannot be a label name")
    return sanitized
