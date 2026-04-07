# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from provide.telemetry.pii import sanitize_payload


def test_parity_default_sensitive_keys_are_exact_match_only() -> None:
    payload = {
        "author_id": "safe-author",
        "spinning_wheel": "safe-spin",
        "glassness": "safe-word",
    }
    result = sanitize_payload(payload, enabled=True)
    assert result == payload
