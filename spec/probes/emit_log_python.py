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

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger.core import configure_logging, get_logger

config = TelemetryConfig.from_env()
configure_logging(config, force=True)
log = get_logger("probe")
log.info("log.output.parity")
