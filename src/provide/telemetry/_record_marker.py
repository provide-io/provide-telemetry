# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The marker on a LogRecord this SDK has already hardened and sanitized.

The fan-out handler on the root logger also receives every plain stdlib record,
and those still need hardening and PII sanitization; a record the SDK produced
itself must not get them twice. A second pass over a rendered line would
truncate the whole JSON line at the attribute cap, and a second pass over a
receipt line would redact its digest, emit another receipt, and loop.

The marker is an identity, not a value, so no ``extra=`` a caller passes can
claim it. It lives in a module with no imports so that ``receipts`` can use it
without pulling the logger in.
"""

from __future__ import annotations

PIPELINE_RECORD_KEY = "__provide_telemetry_pipeline_record__"
PIPELINE_RECORD_MARKER = object()
