#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Diff each SDK's observed config defaults against the canonical spec.

`config_defaults` in spec/telemetry-api.yaml declares, per variable, its type,
its default, and which SDKs it applies to. This gate runs a per-language probe
that reports the same three facts *observed from that SDK's real default config
object* — never copied from the YAML — and reports an exact diff.

Strictness is the default: an absent toolchain fails rather than skipping, so a
language that was never exercised cannot report parity. Pass
--allow-missing-runtimes to downgrade that to a skip for local work.

    python spec/check_config_parity.py --language python
    python spec/check_config_parity.py            # every language
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 — fixed probe commands, no user-supplied shell
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_LANGUAGES = ("python", "typescript", "go", "rust", "csharp")


@dataclass(frozen=True)
class Probe:
    """How to run one language's config probe."""

    language: str
    runtime: str  # executable that must exist for the probe to run
    command: list[str]
    cwd: Path


def _probes() -> dict[str, Probe]:
    return {
        "python": Probe(
            "python",
            "uv",
            ["uv", "run", "python", str(ROOT / "spec" / "probes" / "config_probe_python.py")],
            ROOT,
        ),
        "typescript": Probe(
            "typescript",
            "npx",
            ["npx", "tsx", str(ROOT / "spec" / "probes" / "config_probe_typescript.ts")],
            ROOT / "typescript",
        ),
        "go": Probe(
            "go",
            "go",
            ["go", "run", str(ROOT / "spec" / "probes" / "config_probe_go" / "main.go")],
            ROOT / "go",
        ),
        "rust": Probe(
            "rust",
            "cargo",
            ["cargo", "--locked", "run", "--quiet", "--example", "config_probe", "--"],
            ROOT / "rust",
        ),
        "csharp": Probe(
            "csharp",
            "dotnet",
            [
                "dotnet",
                "run",
                "--project",
                str(ROOT / "csharp" / "probes" / "ConfigProbe" / "ConfigProbe.csproj"),
                "--",
            ],
            ROOT / "csharp",
        ),
    }


def _expected(language: str) -> dict[str, dict[str, str]]:
    """Entries the spec says this SDK must support, keyed by env var."""
    spec = yaml.safe_load((ROOT / "spec" / "telemetry-api.yaml").read_text(encoding="utf-8"))
    expected: dict[str, dict[str, str]] = {}
    for entries in spec["config_defaults"].values():
        for entry in entries:
            applicability = entry.get("applicability") or []
            # YAML `default:` with no value parses as None and means "unset";
            # probes render an unset value as the empty string, so normalize
            # here rather than making every probe emit the string "None".
            default = entry["default"]
            declared_type = entry["type"]
            # A documented, deliberate per-language deviation — e.g. TypeScript
            # lowercases log levels because it maps them onto Pino's vocabulary.
            # Recording it here keeps the canonical value canonical instead of
            # weakening the spec to whatever the loosest SDK happens to do.
            override = (entry.get("overrides") or {}).get(language) or {}
            if "default" in override:
                default = override["default"]
            if "type" in override:
                declared_type = override["type"]
            expected[entry["env"]] = {
                "type": declared_type,
                "default": "" if default is None else str(default),
                "applicable": language in applicability,
                # Some SDKs honour a variable without routing it through the
                # config object — Rust reads the pretty-renderer colours straight
                # from the environment at render time. The variable *is*
                # supported, so applicability stays true, but a probe that
                # inspects the config object cannot see it. Recording that here
                # keeps the difference visible instead of silently loosening the
                # gate or falsely claiming the SDK ignores the knob.
                "probe_visible": override.get("probe_visible", True),
            }
    return expected


def _types_match(language: str, declared: str, observed: str | None) -> bool:
    """Compare declared and observed types, allowing for language type systems.

    TypeScript has a single `number`: 1.0 and 1 are the same value, so a probe
    reading a real config object genuinely cannot tell int from float. It
    reports `number`, which satisfies either. This is a property of the
    language, not a per-variable exception, so it lives here rather than as 21
    duplicated overrides in the spec.
    """
    if declared == observed:
        return True
    return language == "typescript" and observed == "number" and declared in ("int", "float")


def _defaults_match(declared_type: str, declared: str, observed: str | None) -> bool:
    """Compare defaults by value, so 1.0 and 1 agree for a numeric variable.

    Only numeric types get this treatment: for a string variable "1.0" and "1"
    really are different defaults and must still fail.
    """
    if declared == observed:
        return True
    if declared_type not in ("int", "float") or observed is None:
        return False
    try:
        return float(declared) == float(observed)
    except ValueError:
        return False


def _run_probe(probe: Probe, env_vars: list[str], *, timeout: int) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603  # nosec B603 — fixed argv, no shell
        [*probe.command, *env_vars],
        cwd=str(probe.cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{probe.language} probe exited {result.returncode}: {result.stderr.strip()[:600]}")
    for line in reversed(result.stdout.splitlines()):
        if line.strip().startswith("{"):
            payload: dict[str, Any] = json.loads(line)
            return payload
    raise RuntimeError(f"{probe.language} probe emitted no JSON line")


def compare(language: str, expected: dict[str, dict[str, str]], observed: dict[str, Any]) -> list[str]:
    """Exact diff of (name, type, default, applicable) tuples."""
    errors: list[str] = []
    entries = observed.get("entries", {})
    for env_var in sorted(expected):
        want = expected[env_var]
        got = entries.get(env_var)
        if got is None:
            errors.append(f"{env_var}: probe reported nothing")
            continue
        if not want["probe_visible"]:
            continue
        if bool(want["applicable"]) != bool(got.get("applicable")):
            state = "supports" if got.get("applicable") else "ignores"
            claim = "applicable" if want["applicable"] else "not applicable"
            errors.append(f"{env_var}: spec says {claim} for {language}, but the SDK {state} it")
            continue
        if not want["applicable"]:
            continue
        if not _types_match(language, want["type"], got.get("type")):
            errors.append(f"{env_var}: type spec={want['type']!r} observed={got.get('type')!r}")
        if not _defaults_match(want["type"], want["default"], got.get("default")):
            errors.append(f"{env_var}: default spec={want['default']!r} observed={got.get('default')!r}")
    unknown = sorted(set(entries) - set(expected))
    if unknown:
        errors.append(f"probe reported variables absent from the spec: {unknown}")
    return errors


def check_language(language: str, *, allow_missing: bool, timeout: int) -> tuple[str, list[str]]:
    """Return (status, errors) where status is pass | fail | skip."""
    probe = _probes()[language]
    if shutil.which(probe.runtime) is None:
        if allow_missing:
            return "skip", []
        return "fail", [
            f"required config-probe runtime unavailable: {probe.runtime} (install it, or pass --allow-missing-runtimes)"
        ]
    expected = _expected(language)
    try:
        observed = _run_probe(probe, sorted(expected), timeout=timeout)
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return "fail", [str(exc)]
    errors = compare(language, expected, observed)
    return ("fail" if errors else "pass"), errors


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--language",
        default=",".join(REQUIRED_LANGUAGES),
        help="Comma-separated languages to check (default: all five)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Accepted for compatibility; strictness is already the default",
    )
    parser.add_argument(
        "--allow-missing-runtimes",
        action="store_true",
        default=False,
        help="Downgrade an absent toolchain from a failure to a skip — never in CI",
    )
    parser.add_argument("--timeout", type=int, default=300, help="Per-probe timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    selected = [s.strip().lower() for s in args.language.split(",") if s.strip()]
    unknown = sorted(set(selected) - set(REQUIRED_LANGUAGES))
    if unknown:
        print(f"unknown language(s): {unknown}", file=sys.stderr)
        return 1

    failed = False
    for language in selected:
        status, errors = check_language(language, allow_missing=args.allow_missing_runtimes, timeout=args.timeout)
        if status == "skip":
            print(f"  [{language:11s}] SKIP  (runtime not installed)")
            continue
        if status == "pass":
            print(f"  [{language:11s}] PASS")
            continue
        failed = True
        print(f"  [{language:11s}] FAIL", file=sys.stderr)
        for error in errors:
            print(f"      - {error}", file=sys.stderr)

    if failed:
        print("\nConfig parity gate failed.", file=sys.stderr)
        return 1
    print("\nConfig parity gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
