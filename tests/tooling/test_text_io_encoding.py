# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Every text read and write in this repository names its encoding.

Python picks the *locale* encoding when a text stream does not name one, and on
Windows that is the ANSI code page — cp1252 on a Western install, not UTF-8, on
3.11 through 3.14 alike. PEP 686 makes UTF-8 the default only in 3.15, and
``requires-python`` here is ``>=3.11``.

That default is why this gate exists rather than a convention. ``spec/
behavioral_fixtures.yaml`` holds emoji, and two parity tests read it with no
encoding. Every byte of ``F0 9F 98 80`` is a valid cp1252 character, so on the
Windows leg the read *succeeded* and produced mojibake — no exception, no
failing assertion, because neither test happened to look at the emoji category.
The corruption was one new assertion away from being a Windows-only failure
that reproduced nowhere else.

Scope is the whole repository rather than ``src/``: the SDK itself has never had
an offender, and every one of the fifty-one this gate first caught was in
tooling, tests and probes — which is exactly the code that decides whether the
Windows leg tells the truth.

Binary modes are exempt, having no encoding to name.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Generated, vendored or downloaded trees, matched against the path relative to
# the root. mutants/ is mutmut's rewritten copy of the project, so from a real
# checkout it mirrors whatever src/ does and scanning it twice is meaningless —
# but the suite also runs from *inside* that copy, where "mutants" is the root
# and must not match anything.
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "mutants",
        "node_modules",
        "target",
    }
)

_TEXT_METHODS = frozenset({"read_text", "write_text"})


def _python_files() -> list[Path]:
    """Every Python file under the root, skipping generated and vendored trees.

    Matched on the path *relative to the root*, not the absolute one. mutmut
    runs this suite from inside its own ``mutants/`` copy of the project, so
    every absolute path there contains "mutants" — an absolute match skipped the
    entire tree and the scan found nothing, which the sweep assertion below
    caught. Relative matching skips ``mutants/`` from a real checkout and scans
    the copy on its own terms.
    """
    return [
        path
        for path in sorted(_REPO_ROOT.rglob("*.py"))
        if not _SKIP_DIRS.intersection(path.relative_to(_REPO_ROOT).parts)
    ]


def _is_binary_mode(mode: ast.expr | None) -> bool:
    return isinstance(mode, ast.Constant) and "b" in str(mode.value)


def _missing_encoding(call: ast.Call) -> bool:
    """True when call is a text read/write that does not name an encoding."""
    if any(keyword.arg == "encoding" for keyword in call.keywords):
        return False
    func = call.func

    if isinstance(func, ast.Attribute) and func.attr in _TEXT_METHODS:
        return True

    # Path.open(mode) — the mode is positional and optional.
    if isinstance(func, ast.Attribute) and func.attr == "open":
        mode = next((arg for arg in call.args if isinstance(arg, ast.Constant)), None)
        return not _is_binary_mode(mode)

    # Builtin open(path, mode).
    if isinstance(func, ast.Name) and func.id == "open":
        return not _is_binary_mode(call.args[1] if len(call.args) > 1 else None)

    return False


def _offenders(path: Path, label: str | None = None) -> list[str]:
    """Every offending call in path, as "<label>:<line>" strings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    name = label if label is not None else str(path.relative_to(_REPO_ROOT))
    return [
        f"{name}:{node.lineno}" for node in ast.walk(tree) if isinstance(node, ast.Call) and _missing_encoding(node)
    ]


def test_every_text_read_and_write_names_its_encoding() -> None:
    """A text stream without an explicit encoding is a Windows bug in waiting."""
    found = [entry for path in _python_files() for entry in _offenders(path)]
    assert not found, "text I/O without encoding=; these decode as cp1252 on Windows:\n  " + "\n  ".join(found)


def test_the_scan_actually_reaches_the_repository() -> None:
    """A scan that silently matched nothing would pass the gate above forever.

    The skip list is a directory-name match, so one careless entry — "tests",
    say — empties the sweep without failing anything.
    """
    files = _python_files()
    assert len(files) > 100, f"only {len(files)} files scanned; the skip list is swallowing the repo"
    names = {path.name for path in files}
    assert "conftest.py" in names
    assert any(path.parts[-3:-1] == ("provide", "telemetry") for path in files), "src/ is not being scanned"


def test_the_detector_recognises_each_offending_form(tmp_path: Path) -> None:
    """Pin what counts, so the gate cannot be quietly narrowed to nothing."""
    source = tmp_path / "sample.py"
    source.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "p = Path('x')",
                "p.read_text()",  # 3
                "p.write_text('a')",  # 4
                "p.open('w')",  # 5
                "open('x')",  # 6
                "open('x', 'w')",  # 7
            ]
        ),
        encoding="utf-8",
    )
    assert [entry.rsplit(":", 1)[1] for entry in _offenders(source, "sample")] == ["3", "4", "5", "6", "7"]


def test_the_detector_accepts_the_correct_forms(tmp_path: Path) -> None:
    """Named encodings and binary modes are not offenders."""
    source = tmp_path / "sample.py"
    source.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "p = Path('x')",
                "p.read_text(encoding='utf-8')",
                "p.write_text('a', encoding='utf-8')",
                "p.open('w', encoding='utf-8')",
                "p.open('rb')",
                "open('x', encoding='utf-8')",
                "open('x', 'rb')",
                "p.read_bytes()",
                "p.write_bytes(b'a')",
            ]
        ),
        encoding="utf-8",
    )
    assert _offenders(source, "sample") == []
