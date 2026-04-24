#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Gate: every ``# pragma: no mutate`` (and optionally ``# pragma: no cover``)
in ``src/provide/telemetry/**/*.py`` must carry a human-readable reason.

Rationale: mutation exemptions are ratchets. Without a documented reason the
cost of later auditing "is this exemption still justified?" grows unbounded.
This gate forces the author of each exemption to record *why* the mutation
would be equivalent, unreachable, or otherwise non-semantic.

Accepted forms::

    x = 1  # pragma: no mutate -- reason text
    x = 1  # pragma: no mutate — reason text
    x = 1  # pragma: no mutate  # reason text

Any bare ``# pragma: no mutate`` with no trailing reason is reported. The
script is report-only by default; ``--fix`` is reserved for future use and
currently just prints the same report plus guidance.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPO_ROOT / "src" / "provide" / "telemetry"

# Pragmas we govern. ``no mutate`` is always checked; ``no cover`` is opt-in
# via ``--kinds``. Extending the tuple lets future governance layers enforce
# reasons on additional pragma dialects without rewriting the scanner.
DEFAULT_KINDS: tuple[str, ...] = ("no mutate",)
ALL_KINDS: tuple[str, ...] = ("no mutate", "no cover")

# Match the pragma itself. We intentionally tolerate multiple spaces and also
# the rarer form ``# pragma:no mutate`` (no space after the colon).
_PRAGMA_RE_TEMPLATE = r"#\s*pragma\s*:\s*{kind}\b"

# A reason is "anything non-empty after an em-dash, double-dash, or a second
# ``#`` comment marker". We normalise the trailing text to check emptiness.
_REASON_SEPARATORS = ("—", "--", "#")


@dataclass(frozen=True)
class Violation:
    """A single bare pragma occurrence."""

    path: Path
    lineno: int
    kind: str
    line: str


def _compile_pragma_regex(kind: str) -> re.Pattern[str]:
    # Allow one or more whitespace chars inside the kind to match "no  mutate"
    # (defensive — the scanner should still flag reason-less variants).
    kind_pattern = re.escape(kind).replace(r"\ ", r"\s+")
    return re.compile(_PRAGMA_RE_TEMPLATE.format(kind=kind_pattern))


def _extract_trailing_reason(line: str, match: re.Match[str]) -> str:
    """Return the trailing reason text after the pragma, stripped.

    Returns an empty string if there is no separator-introduced reason.
    """
    tail = line[match.end() :]
    # Strip an immediately following ``:`` from pragmas like
    # ``# pragma: no mutate: reason`` — treat ``:`` as a separator too.
    stripped = tail.lstrip()
    for sep in (*_REASON_SEPARATORS, ":"):
        if stripped.startswith(sep):
            return stripped[len(sep) :].strip()
    return ""


def _line_has_bare_pragma(line: str, regex: re.Pattern[str]) -> bool:
    match = regex.search(line)
    if match is None:
        return False
    reason = _extract_trailing_reason(line, match)
    return reason == ""


def iter_python_files(root: Path) -> Iterable[Path]:
    """Yield every ``*.py`` file beneath ``root`` in deterministic order."""
    if root.is_file() and root.suffix == ".py":
        yield root
        return
    yield from sorted(root.rglob("*.py"))


def scan_file(path: Path, kinds: Sequence[str]) -> list[Violation]:
    """Scan a single file and return any bare-pragma violations."""
    regexes = {kind: _compile_pragma_regex(kind) for kind in kinds}
    violations: list[Violation] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):  # pragma: no cover -- IO edge
        return violations
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind, regex in regexes.items():
            if _line_has_bare_pragma(line, regex):
                violations.append(Violation(path=path, lineno=lineno, kind=kind, line=line.rstrip()))
    return violations


def scan_paths(paths: Iterable[Path], kinds: Sequence[str]) -> list[Violation]:
    """Scan many roots/files and collect all violations."""
    results: list[Violation] = []
    for root in paths:
        for py in iter_python_files(root):
            results.extend(scan_file(py, kinds))
    return results


def _format_violation(v: Violation, repo_root: Path) -> str:
    try:
        rel = v.path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        rel = v.path
    return f"{rel.as_posix()}:{v.lineno}: bare `# pragma: {v.kind}` (no reason)"


def _guidance(kind: str) -> str:
    return (
        f"Add a reason after the pragma: `# pragma: {kind} — <why>`. "
        "See docs/MUTATION_EXEMPTIONS.md for the exemption policy."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail if any Python source file under src/provide/telemetry carries a "
            "bare `# pragma: no mutate` without a trailing reason."
        ),
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        type=Path,
        default=[DEFAULT_ROOT],
        help="Directories (or files) to scan. Defaults to src/provide/telemetry.",
    )
    parser.add_argument(
        "--kinds",
        nargs="+",
        choices=list(ALL_KINDS),
        default=list(DEFAULT_KINDS),
        help="Which pragma kinds to govern. Defaults to 'no mutate'.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="(reserved) — currently behaves the same as report mode.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the pass message; only print on failure.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    violations = scan_paths(args.roots, args.kinds)

    if not violations:
        if not args.quiet:
            scope = ", ".join(f"'{k}'" for k in args.kinds)
            print(f"pragma-reasons check passed: every {scope} exemption has a reason.")
        return 0

    print(f"pragma-reasons check failed: {len(violations)} bare pragma(s) without a reason:")
    for v in violations:
        print(f"  {_format_violation(v, REPO_ROOT)}")
    # Print guidance once per distinct kind seen.
    for kind in sorted({v.kind for v in violations}):
        print(f"  -> {_guidance(kind)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
