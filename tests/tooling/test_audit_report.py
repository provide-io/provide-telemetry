# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""A scanner that inventories nothing is broken, not clean."""

from __future__ import annotations

import pytest

from ci.audit_report import Finding, assert_non_empty_inventory, fail_on_findings

pytestmark = pytest.mark.tooling


def _finding() -> Finding:
    return Finding(
        package="example",
        installed="1.0.0",
        advisory="GHSA-xxxx-xxxx-xxxx",
        severity="high",
        fixed_in="1.0.1",
    )


def test_zero_inventory_raises() -> None:
    with pytest.raises(SystemExit) as excinfo:
        assert_non_empty_inventory(0, ecosystem="python", minimum=10)
    assert excinfo.value.code != 0


def test_inventory_below_minimum_raises() -> None:
    with pytest.raises(SystemExit):
        assert_non_empty_inventory(9, ecosystem="python", minimum=10)


def test_inventory_at_minimum_is_accepted() -> None:
    assert_non_empty_inventory(10, ecosystem="python", minimum=10)


def test_no_findings_exits_zero() -> None:
    assert fail_on_findings([], ecosystem="python") == 0


def test_any_finding_exits_non_zero() -> None:
    assert fail_on_findings([_finding()], ecosystem="python") == 1


def test_finding_is_reported_with_its_advisory_and_fix(capsys: pytest.CaptureFixture[str]) -> None:
    fail_on_findings([_finding()], ecosystem="python")
    err = capsys.readouterr().err
    assert "GHSA-xxxx-xxxx-xxxx" in err
    assert "1.0.1" in err
    assert "example" in err


def test_clean_result_names_the_ecosystem(capsys: pytest.CaptureFixture[str]) -> None:
    fail_on_findings([], ecosystem="csharp")
    assert "csharp" in capsys.readouterr().out


def test_csharp_report_parsing_extracts_transitive_vulnerabilities() -> None:
    from ci.audit_csharp import _findings_for

    project = {
        "frameworks": [
            {
                "framework": "net10.0",
                "transitivePackages": [
                    {
                        "id": "Example.Pkg",
                        "resolvedVersion": "1.0.0",
                        "vulnerabilities": [{"severity": "High", "advisoryurl": "https://example.test/GHSA"}],
                    }
                ],
            }
        ]
    }
    findings = _findings_for(project)
    assert len(findings) == 1
    assert findings[0].package == "Example.Pkg"
    assert findings[0].severity == "High"


def test_csharp_report_parsing_ignores_a_project_with_no_frameworks() -> None:
    from ci.audit_csharp import _findings_for

    assert _findings_for({"path": "/some/project.csproj"}) == []
