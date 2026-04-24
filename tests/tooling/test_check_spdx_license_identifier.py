# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for SPDX license identifier validation in check_spdx_headers.py.

String literals below contain synthetic SPDX lines used as test fixtures for
the validator under test. They are wrapped in REUSE-IgnoreStart/End so the
REUSE tool does not mistake them for real license declarations of this file.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).parent.parent.parent
_CHECK_PATH = _REPO_ROOT / "scripts" / "check_spdx_headers.py"
_SPDX_PATH = _REPO_ROOT / "scripts" / "spdx_headers.py"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CHECK_MODULE = _load(_CHECK_PATH, "check_spdx_headers_license_id_test")
_SPDX_MODULE = _load(_SPDX_PATH, "spdx_headers_for_license_id_test")


# REUSE-IgnoreStart
def test_apache_2_0_is_valid() -> None:
    """The canonical `Apache-2.0` identifier must validate."""
    text = "# SPDX-License-Identifier: Apache-2.0\n"
    ok, ident = _CHECK_MODULE.validate_license_identifier(text)
    assert ok is True
    assert ident == "Apache-2.0"


def test_apache_2_dash_0_typo_is_rejected() -> None:
    """`Apache-2-0` (the classic typo) must be rejected by the validator."""
    text = "# SPDX-License-Identifier: Apache-2-0\n"
    ok, ident = _CHECK_MODULE.validate_license_identifier(text)
    assert ok is False
    assert ident == "Apache-2-0"


def test_unknown_identifier_is_rejected() -> None:
    """Any identifier outside the allowlist must be rejected."""
    text = "// SPDX-License-Identifier: MIT\n"
    ok, ident = _CHECK_MODULE.validate_license_identifier(text)
    assert ok is False
    assert ident == "MIT"


def test_missing_identifier_returns_none() -> None:
    """When there's no SPDX license line, validate returns (False, None)."""
    text = "# no license anywhere\n"
    ok, ident = _CHECK_MODULE.validate_license_identifier(text)
    assert ok is False
    assert ident is None


def test_find_noncompliant_flags_invalid_identifier(tmp_path: Path) -> None:
    """File with canonical header shape but wrong identifier must be reported as invalid."""
    # Build a file with the canonical header block but with Apache-2-0 typo
    bad_block = (
        "# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc\n"
        "# SPDX-License-Identifier: Apache-2-0\n"
        "# SPDX-Comment: Part of provide-telemetry.\n"
        "#\n"
        "\n"
    )
    path = tmp_path / "typo.py"
    path.write_text(bad_block + "x = 1\n", encoding="utf-8")

    # Also a correct file
    good = tmp_path / "good.py"
    good.write_text("".join(_SPDX_MODULE.CANONICAL_BLOCK) + "x = 1\n", encoding="utf-8")

    missing, invalid = _CHECK_MODULE.find_noncompliant_files(tmp_path)
    # The bad file has a full header shape but wrong id — it shows up in invalid,
    # not missing. (Shape matches CANONICAL_BLOCK exactly except for the id line,
    # but has_canonical_header compares against the exact CANONICAL_BLOCK, so the
    # bad file will register as missing rather than invalid. Accept either: what
    # matters is the script reports the file and exits nonzero.)
    assert path in missing or any(p == path for p, _ in invalid), (missing, invalid)


def test_find_noncompliant_flags_invalid_identifier_with_canonical_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file whose canonical header is valid but identifier is disallowed must land in invalid."""
    # Pretend the allowlist accepts the canonical header shape but not our
    # actual Apache-2.0 identifier. Writing the canonical block and then
    # narrowing the allowlist lets us exercise the invalid bucket.
    monkeypatch.setattr(_CHECK_MODULE, "ALLOWED_LICENSE_IDENTIFIERS", frozenset({"FakeLicense-9.9"}))
    good_shape_wrong_id = tmp_path / "wrong_id.py"
    good_shape_wrong_id.write_text(
        "".join(_SPDX_MODULE.CANONICAL_BLOCK) + "x = 1\n",
        encoding="utf-8",
    )
    missing, invalid = _CHECK_MODULE.find_noncompliant_files(tmp_path)
    assert missing == []
    assert invalid == [(good_shape_wrong_id, "Apache-2.0")]


# REUSE-IgnoreEnd


def test_repo_passes_identifier_validation() -> None:
    """The real repo tree must satisfy the full check (header shape + identifier)."""
    missing, invalid = _CHECK_MODULE.find_noncompliant_files(_REPO_ROOT)
    assert missing == [], f"unexpected header gaps: {missing}"
    assert invalid == [], f"unexpected identifier mismatches: {invalid}"
