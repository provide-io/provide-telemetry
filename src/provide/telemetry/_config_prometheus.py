# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Parsing and validation for the Prometheus metrics settings.

See the prometheus_metrics section of spec/telemetry-api.yaml. Invalid values
raise ConfigurationError, as for the other enum-valued settings, except in
OTEL_METRICS_EXPORTER, whose unusable entries are warned about and ignored.
"""

from __future__ import annotations

from collections.abc import Mapping

from provide.telemetry.exceptions import ConfigurationError

EXPORTER_OTLP = "otlp"
EXPORTER_PROMETHEUS = "prometheus"
EXPORTER_NONE = "none"
# Registered for OTEL_METRICS_EXPORTER by the OTel spec, not implemented here.
UNSUPPORTED_EXPORTERS = ("console", "logging")
WARNING_SEPARATOR = "; "
LISTEN_VALUES = ("false", "true", "auto")
MAX_PORT = 65535
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9464
DEFAULT_PATH = "/metrics"
DEFAULT_TRANSLATION = "UnderscoreEscapingWithSuffixes"
TRANSLATION_STRATEGIES = (
    "UnderscoreEscapingWithSuffixes",
    "UnderscoreEscapingWithoutSuffixes",
    "NoUTF8EscapingWithSuffixes",
    "NoTranslation",
)


def parse_metrics_exporters(raw: str | None, strict: bool = False) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Parse OTEL_METRICS_EXPORTER into (exporters, warnings).

    Entries are split on commas, trimmed and lowercased; empty ones are dropped.
    Empty input means ("otlp",) and "none" alone means no exporters. Anything
    else this SDK cannot export to is dropped with a warning, as the OTel
    environment-variable spec asks of an unrecognised enum value; see
    prometheus_metrics.metrics_exporter_warnings. strict turns any warning into
    a ConfigurationError.
    """
    names = [part.strip().lower() for part in (raw or "").split(",") if part.strip()]
    if names and all(n == EXPORTER_NONE for n in names):
        return (), ()
    warnings: list[str] = []
    for name in dict.fromkeys(names):
        if name in UNSUPPORTED_EXPORTERS:
            warnings.append(f"OTEL_METRICS_EXPORTER: {name} is not supported by provide-telemetry, ignored")
        elif name not in (EXPORTER_OTLP, EXPORTER_PROMETHEUS, EXPORTER_NONE):
            warnings.append(f"OTEL_METRICS_EXPORTER: unknown exporter {name}, ignored")
    if EXPORTER_NONE in names:
        warnings.append("OTEL_METRICS_EXPORTER: none cannot be combined with other exporters, ignored")
    exporters = tuple(n for n in names if n in (EXPORTER_OTLP, EXPORTER_PROMETHEUS))
    if names and not exporters:
        warnings.append("OTEL_METRICS_EXPORTER: no supported exporter left, using otlp")
    if strict and warnings:
        raise ConfigurationError(f"PROVIDE_TELEMETRY_STRICT_CONFIG: {WARNING_SEPARATOR.join(warnings)}")
    return exporters or (EXPORTER_OTLP,), tuple(warnings)


def validate_exporters(exporters: tuple[str, ...]) -> None:
    """Reject an exporter list built in code with a name the env parser would refuse."""
    unknown = [e for e in exporters if e not in (EXPORTER_OTLP, EXPORTER_PROMETHEUS)]
    if unknown:
        raise ConfigurationError(f"metrics exporters: unknown {unknown!r}")


def parse_port(raw: str | None) -> int:
    """Parse OTEL_EXPORTER_PROMETHEUS_PORT: an integer in 0-65535, 0 meaning any free port."""
    value = (raw or "").strip()
    if not value:
        return DEFAULT_PORT
    try:
        port = int(value)
    except ValueError:
        raise ConfigurationError(f"OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got {value!r}") from None
    validate_port(port)
    return port


def validate_port(port: int) -> None:
    if port < 0 or port > MAX_PORT:
        raise ConfigurationError(f"OTEL_EXPORTER_PROMETHEUS_PORT: want an integer in 0-65535, got {port}")


def validate_listen(listen: str) -> None:
    if listen not in LISTEN_VALUES:
        raise ConfigurationError(f"PROVIDE_METRICS_PROMETHEUS_LISTEN: want false, true or auto, got {listen!r}")


def validate_path(path: str) -> None:
    if not path.startswith("/") or "?" in path or "#" in path:
        raise ConfigurationError(
            f"PROVIDE_METRICS_PROMETHEUS_PATH: want a path starting with / and no query or fragment, got {path!r}"
        )


def validate_translation(translation: str) -> None:
    if translation not in TRANSLATION_STRATEGIES:
        raise ConfigurationError(f"PROVIDE_METRICS_PROMETHEUS_TRANSLATION: unknown strategy {translation!r}")


def env_str(data: Mapping[str, str], key: str, default: str) -> str:
    """A trimmed string setting; empty or unset means the default."""
    return (data.get(key) or "").strip() or default
