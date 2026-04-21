#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Install dependencies for the behavioral-parity CI job.

Installs Python and TypeScript deps needed to run all four language parity
test suites. Go and Rust deps are managed by their own toolchains (go.sum,
Cargo.lock) and do not need a separate install step.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)  # noqa: S603


def main() -> int:
    # Python: install dev dependencies
    _run(["uv", "sync", "--group", "dev", "--extra", "otel"], _REPO_ROOT)
    # TypeScript: install npm dependencies
    _run(["npm", "ci"], _REPO_ROOT / "typescript")
    return 0


if __name__ == "__main__":
    sys.exit(main())
