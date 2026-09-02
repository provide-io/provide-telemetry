# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-language check that callsite fields name the caller.

The log-output parity pass runs with ``PROVIDE_LOG_INCLUDE_CALLER=false`` so the
compared record is deterministic, and every other harness in the repo does the
same. The consequence is that the one behaviour the knob controls was never
compared, and four SDKs drifted apart unseen: Python emitted ``filename`` /
``lineno``, TypeScript emitted ``caller_file`` / ``caller_line``, and Go and C#
emitted nothing while the spec declared the variable applicable to all four.

This pass turns the knob on and asserts the canonical contract from
``telemetry-api.yaml``'s ``callsite_fields``: ``filename`` is the base name of
the *caller's* source file, and ``lineno`` is a positive integer.

It is deliberately two-sided against ``spec/config_honoured_gaps.yaml``:

* a language with a declared gap must emit **nothing** — if it emits, the gap is
  stale and the register entry has to go;
* a language without one must emit **both** fields, correctly attributed.

That is what stops the register from being mere documentation. Removing an entry
without implementing fails here, and implementing without removing the entry
fails here too.

Split out of ``parity_probe_support`` to keep that file under its 500-LOC
ceiling, following ``_runtime_probe``: the parent does not import from this
module, so there is no cycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from parity_probe_support import ProbeRunner

_CALLER_ENV_VAR = "PROVIDE_LOG_INCLUDE_CALLER"


def _parent() -> Any:
    """The parity_probe_support module, however it was loaded.

    Same resolution order as ``_runtime_probe._shared``: the canonical entry
    first, then any alias loaded from the same file (tooling and tests load it
    through ``spec_from_file_location``, and a fresh canonical import would
    create a second module object and discard their monkeypatches), then a
    canonical import as a fallback. This takes the module rather than
    ``SharedHelpers`` because it needs the probe runners and the runner itself,
    which that view does not carry.
    """
    import sys

    canonical = sys.modules.get("parity_probe_support")
    if canonical is not None:
        return canonical

    for mod in list(sys.modules.values()):
        mod_file = getattr(mod, "__file__", None) if mod is not None else None
        if mod_file and mod_file.endswith("parity_probe_support.py"):
            return mod

    import parity_probe_support  # type: ignore[import-not-found]

    return parity_probe_support


def _fixture(repo: Path) -> dict[str, Any]:
    """The ``caller_probe`` block from behavioral_fixtures.yaml."""
    path = repo / "spec" / "behavioral_fixtures.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for section in data.values():
        if isinstance(section, dict) and "caller_probe" in section:
            block = section["caller_probe"]
            if isinstance(block, dict):
                return block
    return {}


def _applicable_languages(repo: Path) -> set[str]:
    """Languages the spec says must honour PROVIDE_LOG_INCLUDE_CALLER."""
    spec = yaml.safe_load((repo / "spec" / "telemetry-api.yaml").read_text(encoding="utf-8"))
    for entries in spec["config_defaults"].values():
        for entry in entries:
            if entry.get("env") == _CALLER_ENV_VAR:
                return set(entry.get("applicability") or [])
    return set()


def _declared_gaps(repo: Path) -> set[str]:
    """Languages that declare they parse the knob without honouring it."""
    path = repo / "spec" / "config_honoured_gaps.yaml"
    if not path.exists():
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        entry["lang"]
        for entry in (data.get("honoured_gaps") or [])
        if isinstance(entry, dict) and entry.get("env") == _CALLER_ENV_VAR
    }


def _check_record(
    language: str,
    record: dict[str, object],
    expected_filename: str | None,
    *,
    has_gap: bool,
) -> list[str]:
    """Compare one language's record against the contract. Returns problems."""
    filename = record.get("filename")
    lineno = record.get("lineno")

    if has_gap:
        if filename is None and lineno is None:
            return []
        return [
            f"  {language}: emits callsite fields (filename={filename!r}, lineno={lineno!r}) "
            f"but declares a gap in config_honoured_gaps.yaml — the entry is stale, remove it"
        ]

    problems: list[str] = []
    if filename is None:
        problems.append(f"  {language}: no 'filename' field; the spec applies {_CALLER_ENV_VAR} here")
    elif expected_filename is not None and filename != expected_filename:
        problems.append(
            f"  {language}: filename is {filename!r}, want {expected_filename!r} — "
            "the record names something other than its caller"
        )
    if not isinstance(lineno, int) or isinstance(lineno, bool) or lineno <= 0:
        problems.append(f"  {language}: 'lineno' is {lineno!r}, want a positive integer")
    return problems


def run_caller_output_check(
    repo: Path,
    selected: set[str],
    cargo_bin: str,
    cargo_env: dict[str, str],
    probe_env: dict[str, str],
    *,
    verbose: bool = False,
    timeout: int = 60,
) -> bool:
    """Run the probes with callsite capture on. Returns True if all pass."""
    parent = _parent()
    fixture = _fixture(repo)
    if not fixture:
        print("  (no caller_probe fixture — skipping)")
        return True

    applicable = _applicable_languages(repo)
    gaps = _declared_gaps(repo)
    expected = fixture.get("expected_filename") or {}
    case_env = {**probe_env, **(fixture.get("env") or {})}

    runners: list[ProbeRunner] = [
        r for r in parent._probe_runners(repo, cargo_bin, cargo_env) if r.name in selected and r.name in applicable
    ]

    print()
    print("── Callsite attribution ────────────────────────────")
    if not runners:
        print("  (no applicable language selected — skipping)")
        return True

    all_ok = True
    for runner in runners:
        output, err = parent._run_probe(runner, case_env, timeout=timeout)
        if err:
            print(f"  [{runner.label:12s}] PROBE ERROR: {err}")
            all_ok = False
            continue
        raw = parent._extract_json_line(output)
        if raw is None:
            print(f"  [{runner.label:12s}] NO JSON LINE in output")
            if verbose:
                print(f"    output: {output[:300]!r}")
            all_ok = False
            continue

        record = parent._normalize_log_record(raw)
        has_gap = runner.name in gaps
        problems = _check_record(
            runner.name,
            record,
            expected.get(runner.name),
            has_gap=has_gap,
        )
        if problems:
            for problem in problems:
                print(problem)
            all_ok = False
            continue

        if has_gap:
            print(f"  [{runner.label:12s}] declared gap: emits no callsite fields, as registered")
        else:
            print(f"  [{runner.label:12s}] {json.dumps({k: record.get(k) for k in ('filename', 'lineno')})}")

    if all_ok:
        print("  MATCH: every applicable SDK agrees with the declared state")
    return all_ok
