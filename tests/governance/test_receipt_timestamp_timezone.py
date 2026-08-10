# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Receipt timestamps are UTC regardless of the host's timezone.

Split out of test_receipts.py, which sat at exactly 500 lines: adding the
platform guard below pushed it past the repo's limit, and the allowlist is for
pre-existing violators with split plans, not for new growth.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from provide.telemetry.receipts import receipt_timestamp

# time.tzset() is POSIX-only. Windows has no runtime API to rezone a live
# process, and mypy targeting Windows types the time module without the
# attribute at all — which is what turned the Windows quality job red while
# every Linux job stayed green. Bound through getattr so the module type-checks
# on either platform, and skipped where it is absent rather than quietly
# passing a test that never changed the zone.
_TZSET: Callable[[], None] | None = getattr(time, "tzset", None)


@pytest.mark.skipif(_TZSET is None, reason="time.tzset is POSIX-only; Windows cannot rezone a live process")
def test_receipt_timestamp_is_utc_whatever_the_host_timezone_is() -> None:
    """The trailing Z is a claim, so the clock behind it has to be UTC.

    A default of ``datetime.now()`` reads the host's local zone and still spells
    the result ``Z``, which on a machine outside UTC backdates or postdates every
    receipt in the audit trail by the local offset — silently, and only on that
    machine. Pinned here with the process forced seven hours off UTC.
    """
    assert _TZSET is not None  # guaranteed by the skipif; narrows the type
    original = os.environ.get("TZ")
    os.environ["TZ"] = "XYZ-07"  # POSIX spelling for "local time is UTC+7".
    _TZSET()
    try:
        before = datetime.now(UTC)
        stamped = receipt_timestamp()
        after = datetime.now(UTC)
    finally:
        if original is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = original
        _TZSET()

    parsed = datetime.strptime(stamped, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    # A second of slack for the strftime truncation, against a seven-hour skew.
    assert before - timedelta(seconds=1) <= parsed <= after + timedelta(seconds=1)
