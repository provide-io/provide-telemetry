#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Emit one canonical JSON log line to stderr for cross-language parity checking.

Env vars (set by run_behavioral_parity.py --check-output before invoking):
  PROVIDE_LOG_FORMAT=json
  PROVIDE_TELEMETRY_SERVICE_NAME=probe
  PROVIDE_LOG_INCLUDE_TIMESTAMP=false
  PROVIDE_LOG_LEVEL=INFO
"""

from __future__ import annotations

import os
import sys

# Ensure the source tree is importable when run from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from provide.telemetry import get_logger, set_trace_context, setup_telemetry

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "b7ad6b7169203331"

setup_telemetry()
set_trace_context(TRACE_ID, SPAN_ID)
log = get_logger("probe")
log.info("log.output.parity")
