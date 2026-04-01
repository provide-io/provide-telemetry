#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Security hardening features: input sanitization, secret detection, protocol guards.

Demonstrates:
  1. Control character stripping from log attributes
  2. Attribute value truncation (configurable max length)
  3. Attribute count limiting
  4. Automatic secret detection and redaction (AWS keys, JWTs, GitHub tokens)
  5. Configurable nesting depth limits
"""

from __future__ import annotations

from provide.telemetry import get_logger, setup_telemetry, shutdown_telemetry
from provide.telemetry.pii import sanitize_payload


def main() -> None:
    setup_telemetry()
    log = get_logger("security-demo")

    print("=== Security Hardening Demo ===\n")

    # 1. Control characters stripped from log output
    print("1. Control character stripping:")
    log.info("security.demo.control_chars", data="clean\x00hidden\x01bytes\x7fremoved")
    print("   (null bytes and control chars silently removed)\n")

    # 2. Oversized values truncated
    print("2. Value truncation (default 1024 chars):")
    huge_value = "x" * 2000
    log.info("security.demo.truncation", big_field=huge_value)
    print(f"   Input: {len(huge_value)} chars → truncated to 1024\n")

    # 3. Secret detection in values
    print("3. Automatic secret detection:")
    payload = {
        "user": "alice",
        "debug_output": "AKIAIOSFODNN7EXAMPLE",  # pragma: allowlist secret
        "auth_header": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",  # pragma: allowlist secret
        "notes": "normal text is fine",
    }
    cleaned = sanitize_payload(payload, enabled=True)
    for k, v in cleaned.items():
        print(f"   {k}: {v}")
    print()

    # 4. Nesting depth protection
    print("4. Nesting depth limit (default 8):")
    deep = {"l1": {"l2": {"l3": {"l4": {"l5": {"l6": {"l7": {"l8": {"l9": "deep"}}}}}}}}}
    sanitized = sanitize_payload(deep, enabled=True, max_depth=4)
    print(f"   Sanitized with max_depth=4: {sanitized}\n")

    # 5. Environment variable configuration
    print("5. Configurable via environment:")
    print("   PROVIDE_SECURITY_MAX_ATTR_VALUE_LENGTH=2048")
    print("   PROVIDE_SECURITY_MAX_ATTR_COUNT=128")
    print("   PROVIDE_SECURITY_MAX_NESTING_DEPTH=4")

    shutdown_telemetry()
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
