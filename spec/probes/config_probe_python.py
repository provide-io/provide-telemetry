#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Emit observed config metadata for the Python SDK.

The probe never reads spec/telemetry-api.yaml. It determines applicability
*differentially*: build the config with a clean environment to get the
baseline, then rebuild it once per variable with that variable set to a
distinctive value. A variable this SDK parses changes the config; one it
ignores leaves the config identical. The reported default and type come from
the baseline config object, not from any declaration.

Output (one JSON line on stdout):
    {"language": "python", "entries": {"PROVIDE_LOG_LEVEL":
        {"type": "str", "default": "INFO", "applicable": true}}}
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from provide.telemetry.config import TelemetryConfig  # noqa: E402

# Values chosen to differ from every default in the spec, so "config changed"
# is never a coincidence. Both bool probes are tried: a variable defaulting to
# true only moves when set false, and vice versa. The list also has to contain
# a *valid* value for each validated field — a log level or renderer name that
# fails validation proves the variable is read, but raises before any config
# object exists to diff.
_PROBE_VALUES = (
    "DEBUG",
    "json",
    "red",  # validated ANSI colour names
    "3",  # small int — retries are capped, so 1327 is rejected
    "1327",
    "0.4271",
    "probe-sentinel-value",
    "false",
    "true",
    "http://probe.invalid:4318",
    "probe-module=DEBUG",  # module-level overrides: name=<valid level>
    "probe-key=probe-value",
)

# Environment prefixes the config reads. Everything under them is cleared so a
# developer's own PROVIDE_*/OTEL_* settings cannot leak into the baseline.
_OWNED_PREFIXES = ("PROVIDE_", "OTEL_")


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(_OWNED_PREFIXES)}


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested config dataclass into dotted-path -> scalar."""
    flat: dict[str, Any] = {}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            flat.update(_flatten(getattr(obj, f.name), f"{prefix}{f.name}."))
        return flat
    if isinstance(obj, dict):
        for key in sorted(obj):
            flat[f"{prefix}{key}"] = obj[key]
        return flat
    flat[prefix.rstrip(".")] = obj
    return flat


def _build(env: dict[str, str]) -> dict[str, Any]:
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        return _flatten(TelemetryConfig.from_env())
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _render(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (tuple, list)):
        return ",".join(str(v) for v in value)
    return str(value)


def observe(env_vars: list[str]) -> dict[str, dict[str, Any]]:
    base_env = _clean_env()
    baseline = _build(base_env)
    entries: dict[str, dict[str, Any]] = {}

    for env_var in env_vars:
        changed_key: str | None = None
        rejected = False
        for probe_value in _PROBE_VALUES:
            try:
                observed = _build({**base_env, env_var: probe_value})
            except Exception:
                rejected = True
                continue
            # Keys added by the probe count too: a dict-valued field such as
            # otlp_headers contributes no baseline keys when it is empty, so
            # comparing only shared keys would read as "the SDK ignores this".
            diff = [k for k in baseline if k in observed and observed[k] != baseline[k]]
            added = sorted(set(observed) - set(baseline))
            if diff:
                changed_key = sorted(diff)[0]
                break
            if added:
                changed_key = added[0]
                # The field existed and was empty; its default is the empty
                # container, which renders as "" with type str.
                entries[env_var] = {"type": "str", "default": "", "applicable": True}
                break
        if env_var in entries:  # settled by the added-key branch above
            continue
        if changed_key is None:
            # `rejected` means validation ran on this variable, so the SDK does
            # parse it — the probe just never found a value it accepts. Report
            # it as applicable with unknown metadata so the comparator flags the
            # gap loudly rather than silently claiming the SDK ignores the knob.
            entries[env_var] = {"type": "", "default": "", "applicable": rejected}
            continue
        default = baseline[changed_key]
        entries[env_var] = {
            "type": _type_name(default),
            "default": _render(default),
            "applicable": True,
        }
    return entries


def main(argv: list[str]) -> int:
    env_vars = argv[1:]
    if not env_vars:
        print("usage: config_probe_python.py ENV_VAR [ENV_VAR ...]", file=sys.stderr)
        return 2
    print(json.dumps({"language": "python", "entries": observe(env_vars)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
