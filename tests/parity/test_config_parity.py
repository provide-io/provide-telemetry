# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Cross-language config parity tests.

Validates Python config parsing against the cross-language spec.
"""

from __future__ import annotations

import pytest


def test_parity_pii_max_depth_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    from provide.telemetry.config import TelemetryConfig

    monkeypatch.setenv("PROVIDE_LOG_PII_MAX_DEPTH", "3")
    cfg = TelemetryConfig.from_env()
    assert cfg.pii_max_depth == 3
