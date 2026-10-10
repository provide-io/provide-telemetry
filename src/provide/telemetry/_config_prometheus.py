# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Parsing and validation for the Prometheus metrics settings.

See the prometheus_metrics section of spec/telemetry-api.yaml. Invalid values
raise ConfigurationError, as for the other enum-valued settings.
"""

from __future__ import annotations

from collections.abc import Mapping

from provide.telemetry.exceptions import ConfigurationError

EXPORTER_OTLP = "otlp"
EXPORTER_PROMETHEUS = "prometheus"
EXPORTER_NONE = "none"
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


def parse_metrics_exporters(raw: str | None) -> tuple[str, ...]:
    """Parse OTEL_METRICS_EXPORTER.

    Entries are split on commas, trimmed and lowercased; empty ones are dropped.
    Empty input means ("otlp",). "none" alone means no exporters and may not be
    combined with another.
    """
    names = [part.strip().lower() for part in (raw or "").split(",") if part.strip()]
    unknown = [n for n in names if n not in (EXPORTER_OTLP, EXPORTER_PROMETHEUS, EXPORTER_NONE)]
    if unknown:
        raise ConfigurationError(f"OTEL_METRICS_EXPORTER: unknown exporter {unknown[0]!r}")
    exporters = tuple(n for n in names if n != EXPORTER_NONE)
    if EXPORTER_NONE in names:
        if exporters:
            raise ConfigurationError("OTEL_METRICS_EXPORTER: none cannot be combined with other exporters")
        return ()
    return exporters or (EXPORTER_OTLP,)


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
