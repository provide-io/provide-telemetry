# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""No release section in a changelog repeats a category heading.

A release is one ``## [version]`` section holding ``### Added``, ``### Fixed``
and the like. Each category belongs there once: a reader looking for what broke
reads ``### Fixed``, and a second ``### Fixed`` further down the same release
holds entries they will never see.

The failure mode is a merge, not a typo. Two branches each append a category to
``[Unreleased]``, both sides are wanted, and a resolution that keeps both keeps
both *headings* — the diff looks purely additive and reads as correct. It
happened six times across three of the five changelogs before anything looked,
because nothing did: the release procedure dates these headings and pushes tags
from them, and no gate had an opinion about their shape.

The check is deliberately narrow. It says nothing about *which* categories a
release may use — the vocabulary here is genuinely inconsistent across history
(``Features``, ``Bug Fixes``, ``Quality``, ``CI/CD`` all appear in early
sections) and rewriting shipped release notes to satisfy a house style would be
a different change with none of this one's value. Repetition inside one release
is a defect under every vocabulary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The five language changelogs. Named rather than globbed: a glob picks up
# whatever a dependency tree happens to vendor, and node_modules alone carries
# hundreds.
_CHANGELOGS = (
    "CHANGELOG.md",
    "csharp/CHANGELOG.md",
    "go/CHANGELOG.md",
    "rust/CHANGELOG.md",
    "typescript/CHANGELOG.md",
)


def _repeated_headings(text: str) -> list[str]:
    """Return one description per category heading repeated within a release."""
    repeats: list[str] = []
    release = "(before the first release heading)"
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.rstrip()
        if stripped.startswith("## "):
            release = stripped.removeprefix("## ").strip()
            seen = set()
        elif stripped.startswith("### "):
            heading = stripped.removeprefix("### ").strip()
            if heading in seen:
                repeats.append(f"line {number}: '{heading}' repeats in '{release}'")
            seen.add(heading)
    return repeats


@pytest.mark.parametrize("relative_path", _CHANGELOGS)
def test_no_release_repeats_a_category_heading(relative_path: str) -> None:
    path = _REPO_ROOT / relative_path
    repeats = _repeated_headings(path.read_text(encoding="utf-8"))
    assert not repeats, (
        f"{relative_path} repeats a category heading inside a release:\n  "
        + "\n  ".join(repeats)
        + "\nMerge the entries under the first heading and delete the second."
    )


def test_every_named_changelog_exists() -> None:
    """A renamed or deleted changelog must fail here, not pass by vacancy."""
    missing = [name for name in _CHANGELOGS if not (_REPO_ROOT / name).is_file()]
    assert not missing, f"named changelogs are missing: {missing}"


def test_the_check_catches_a_repeat() -> None:
    """The shape this gate exists for, as it appeared in the real merge."""
    merged = "## [Unreleased]\n\n### Added\n\n- one\n\n### Fixed\n\n- two\n\n### Added\n\n- three\n"
    assert _repeated_headings(merged) == ["line 11: 'Added' repeats in '[Unreleased]'"]


def test_the_same_category_in_two_releases_is_not_a_repeat() -> None:
    """Every release has its own Fixed; only repetition within one is a defect."""
    two = "## [0.9.0]\n\n### Fixed\n\n- one\n\n## [0.8.1]\n\n### Fixed\n\n- two\n"
    assert _repeated_headings(two) == []
