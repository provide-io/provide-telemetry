# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
