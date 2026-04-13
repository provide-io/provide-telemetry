# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Regression tests for the strippable-governance contract.

These tests verify that:
1. Core telemetry (logging, tracing, metrics, PII, schema, health) works without
   importing any governance symbols.
2. Governance symbols are optional and only available via lazy import.
3. A subprocess with governance files physically absent still runs core telemetry.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Tests: core telemetry without governance
# ---------------------------------------------------------------------------


class TestCoreWithoutGovernance:
    """Core features must work even if governance modules are unavailable."""

    def test_setup_shutdown_works(self) -> None:
        """setup_telemetry / shutdown_telemetry must not require governance."""
        from provide.telemetry import setup_telemetry, shutdown_telemetry
        from provide.telemetry.testing import reset_telemetry_state

        reset_telemetry_state()
        cfg = setup_telemetry()
        assert cfg is not None
        shutdown_telemetry()

    def test_logger_works(self) -> None:
        """get_logger must be callable without governance."""
        from provide.telemetry import get_logger

        log = get_logger("strip-governance-test")
        assert log is not None
        # Emitting a structured log must not raise.
        log.info("no_governance.test.logged", extra="value")

    def test_pii_redacts_without_governance(self) -> None:
        """PII sanitization must redact default-sensitive keys even without governance."""
        from provide.telemetry.pii import replace_pii_rules, sanitize_payload

        replace_pii_rules([])
        payload = {
            "user": "alice",
            "password": "s3cr3t",  # pragma: allowlist secret
            "token": "abc123",
        }
        result = sanitize_payload(payload, enabled=True, max_depth=3)
        assert result.get("password") == "***", "password must be redacted"
        assert result.get("token") == "***", "token must be redacted"
        assert result.get("user") == "alice", "non-sensitive key must pass through"
        # No classification labels without governance (classification.py not imported)
        assert "__password__class" not in result, (
            "classification labels must be absent when classification.py not imported"
        )

    def test_schema_event_validation_works(self) -> None:
        """Event schema validation must work without governance."""
        from provide.telemetry.schema.events import event

        e = event("auth", "login", "success")
        assert str(e) == "auth.login.success"
        assert e.domain == "auth"
        assert e.action == "login"
        assert e.status == "success"

    def test_health_snapshot_works(self) -> None:
        """get_health_snapshot must work without governance."""
        from provide.telemetry.health import get_health_snapshot

        snap = get_health_snapshot()
        assert snap.emitted_logs >= 0
        assert snap.dropped_logs >= 0
        assert snap.emitted_traces >= 0
        assert snap.emitted_metrics >= 0

    def test_sampling_works(self) -> None:
        """Sampling policy must work without governance."""
        from provide.telemetry.sampling import (
            SamplingPolicy,
            get_sampling_policy,
            set_sampling_policy,
        )

        policy = SamplingPolicy(default_rate=0.5)
        set_sampling_policy("logs", policy)
        got = get_sampling_policy("logs")
        assert got.default_rate == 0.5
        # Reset
        set_sampling_policy("logs", SamplingPolicy(default_rate=1.0))

    def test_metrics_counter_works(self) -> None:
        """counter() must work without governance."""
        from provide.telemetry.metrics import counter

        c = counter("no_governance.test.counter")
        assert c is not None
        c.add(1)

    def test_backpressure_policy_works(self) -> None:
        """Backpressure queue policy must work without governance."""
        from provide.telemetry.backpressure import (
            QueuePolicy,
            get_queue_policy,
            set_queue_policy,
        )

        policy = QueuePolicy(logs_maxsize=100, traces_maxsize=100, metrics_maxsize=100)
        set_queue_policy(policy)
        got = get_queue_policy()
        assert got.logs_maxsize == 100
        # Reset
        set_queue_policy(QueuePolicy())


# ---------------------------------------------------------------------------
# Tests: governance symbols are optional (lazy, not required)
# ---------------------------------------------------------------------------


class TestGovernanceIsOptional:
    """Governance symbols must only be loaded on first access, not on import."""

    def test_core_import_does_not_load_governance_modules(self) -> None:
        """Core import must not eagerly pull in governance modules.

        Uses a subprocess to get a clean Python process with no prior imports,
        then checks sys.modules after importing only core symbols.
        """
        script = (
            "import provide.telemetry\n"
            "import sys\n"
            "gov = [k for k in sys.modules if any(g in k for g in"
            " ('classification', 'consent', 'receipts'))]\n"
            "assert not gov, f'governance modules loaded eagerly: {gov}'\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Core import pulled in governance modules:\n{result.stdout}{result.stderr}"

    def test_governance_symbols_are_lazily_imported(self) -> None:
        """Governance symbols must resolve correctly when modules are present."""
        import provide.telemetry as t

        # These must be accessible as attributes (lazy import).
        assert hasattr(t, "ClassificationPolicy")
        assert hasattr(t, "ConsentLevel")
        assert hasattr(t, "RedactionReceipt")


# ---------------------------------------------------------------------------
# Tests: actual file deletion — subprocess with governance files absent
# ---------------------------------------------------------------------------


class TestFilesDeletionProof:
    """Prove that physically removing governance files leaves core telemetry intact.

    Each test copies the installed package to a temp directory, deletes the
    governance files there, then runs a subprocess with that modified path
    injected into PYTHONPATH. This is the strongest possible proof.
    """

    @staticmethod
    def _make_stripped_copy() -> Path:
        """Return path to a temp copy of the package with governance files removed.

        We locate the source via the test file path rather than ``t.__file__``
        because under mutmut the latter resolves to the instrumented temp copy,
        which would transplant trampolines into the subprocess and crash it.
        """
        # Walk up from this test file to the project root (contains pyproject.toml),
        # then descend into src/provide/telemetry/.  This is always the real source
        # tree, even when mutmut has set PYTHONPATH to an instrumented directory.
        _here = Path(__file__).resolve()
        for _parent in _here.parents:
            _candidate = _parent / "src" / "provide" / "telemetry"
            if _candidate.exists():
                pkg_dir = _candidate
                break
        else:
            # Fallback: editable install without src layout
            import provide.telemetry as t

            pkg_dir = Path(t.__file__).parent

        provide_dir = pkg_dir.parent  # .../provide/
        tmpdir = Path(tempfile.mkdtemp())
        stripped = tmpdir / "provide"
        shutil.copytree(provide_dir, stripped)

        # Delete the three governance modules from the copy.
        for name in ("classification.py", "consent.py", "receipts.py"):
            target = stripped / "telemetry" / name
            target.unlink(missing_ok=True)

        return tmpdir

    def test_core_import_works_without_governance_files(self) -> None:
        """Core package imports must succeed even when governance .py files are gone."""
        tmpdir = self._make_stripped_copy()
        try:
            script = (
                "import provide.telemetry\n"
                "from provide.telemetry import setup_telemetry, get_logger\n"
                "assert setup_telemetry is not None\n"
                "assert get_logger is not None\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env={**__import__("os").environ, "PYTHONPATH": str(tmpdir)},
            )
            assert result.returncode == 0, (
                f"Core import failed after stripping governance:\n{result.stdout}{result.stderr}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_pii_redacts_without_governance_files(self) -> None:
        """PII redaction must work even when governance .py files are gone."""
        tmpdir = self._make_stripped_copy()
        try:
            script = (
                "from provide.telemetry.pii import replace_pii_rules, sanitize_payload\n"
                "replace_pii_rules([])\n"
                "payload = {'user': 'alice', 'password': 'TESTPWD'}\n"  # pragma: allowlist secret
                "result = sanitize_payload(payload, enabled=True, max_depth=3)\n"
                "assert result['password'] == '***', f'expected redacted, got {result}'\n"
                "assert '__password__class' not in result, 'no classification without module'\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env={**__import__("os").environ, "PYTHONPATH": str(tmpdir)},
            )
            assert result.returncode == 0, (
                f"PII redaction failed after stripping governance:\n{result.stdout}{result.stderr}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_governance_access_raises_when_files_absent(self) -> None:
        """Accessing governance symbols must raise AttributeError when files are gone."""
        tmpdir = self._make_stripped_copy()
        try:
            script = (
                "import provide.telemetry as t\n"
                "try:\n"
                "    _ = t.ClassificationPolicy\n"
                "    raise AssertionError('expected AttributeError')\n"
                "except (AttributeError, ImportError):\n"
                "    pass  # expected — module is absent\n"
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env={**__import__("os").environ, "PYTHONPATH": str(tmpdir)},
            )
            assert result.returncode == 0, (
                f"Governance access did not raise after stripping:\n{result.stdout}{result.stderr}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
