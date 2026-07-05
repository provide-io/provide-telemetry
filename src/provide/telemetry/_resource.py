# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""OTel ``Resource`` construction shared by the trace and metric providers.

Precedence (cross-language contract, see ``spec/behavioral_fixtures.yaml``)::

    framework default  <  OTEL_* env  <  explicit config

An identity key (``service.name`` / ``deployment.environment`` /
``service.version``) joins the top precedence layer only when its config value
differs from the framework default, so an explicitly named service is never
hijacked by an ambient ``OTEL_RESOURCE_ATTRIBUTES`` while ``OTEL_SERVICE_NAME``
still fills an unset name. Additive env keys (``host.name``, ``k8s.*`` …) merge
through untouched.

The logic here is pure — the actual env *values* are applied by the OTel SDK's
own ``OTELResourceDetector`` inside ``Resource.create``. We only need to know
*which* identity keys the env provides so an unset key can fall back to the
floor instead of shadowing the env layer; that membership is parsed directly
from the environment so this module needs no ``otel`` extra and stays covered
and mutation-tested by the base (non-otel) gate.

Matches Go (``_buildResource``), TypeScript (``buildOtelResource``), and Rust
(``build_resource``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from provide.telemetry.config import TelemetryConfig

__all__ = ["build_resource"]

# (resource attribute key, TelemetryConfig field) for each identity attribute.
_IDENTITY_ATTRS: tuple[tuple[str, str], ...] = (
    ("service.name", "service_name"),
    ("deployment.environment", "environment"),
    ("service.version", "version"),
)


def _env_identity_keys(environ: Mapping[str, str]) -> set[str]:
    """Return which identity resource keys are supplied by OTEL_* env vars."""
    keys: set[str] = set()
    raw = environ.get("OTEL_RESOURCE_ATTRIBUTES")
    if raw:
        for pair in raw.split(","):
            # partition on the first '=' — a value may legitimately contain '='.
            key, sep, _value = pair.partition("=")
            if sep and key.strip():
                keys.add(key.strip())
    if environ.get("OTEL_SERVICE_NAME", "").strip():
        keys.add("service.name")
    return keys


def _resolve_resource_attrs(config: TelemetryConfig, env_keys: set[str]) -> dict[str, str]:
    """Compute the attributes to hand ``Resource.create`` (which also applies env).

    A key is included when the config value is explicit (differs from the
    default) so it wins over env, or — when neither explicit nor env-provided —
    with the framework-default floor value. A key left at the default *and*
    provided by env is omitted so the env layer inside ``Resource.create`` shows
    through.
    """
    defaults = TelemetryConfig()
    resolved: dict[str, str] = {}
    for res_key, field in _IDENTITY_ATTRS:
        value = getattr(config, field)
        default = getattr(defaults, field)
        if value != default:
            resolved[res_key] = value
        elif res_key not in env_keys:
            resolved[res_key] = default
    return resolved


def build_resource(
    config: TelemetryConfig,
    resource_cls: Any,
    environ: Mapping[str, str] | None = None,
) -> Any:
    """Build the layered OTel ``Resource`` for a provider.

    ``resource_cls`` is the SDK ``Resource`` class; ``Resource.create`` runs the
    standard detectors (env, telemetry-sdk) and overlays the resolved explicit
    attributes on top, realizing ``floor < env < explicit``.
    """
    env = os.environ if environ is None else environ
    return resource_cls.create(_resolve_resource_attrs(config, _env_identity_keys(env)))
