# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting surviving mutation-testing mutants in slo.classify_error.

These verify exact string return values, boundary conditions, and the
specific conditional logic to ensure mutations on literals and operators
are detected.
"""

from __future__ import annotations

from provide.telemetry.slo import classify_error


class TestClassifyErrorExactValues:
    """Verify exact string values in every dict key for each branch."""

    def test_timeout_branch_all_values(self) -> None:
        """Timeout exc_name + status_code=None -> timeout branch."""
        r = classify_error("TimeoutError", status_code=None)
        assert r["error.category"] == "timeout"
        assert r["error.severity"] == "info"
        assert r["error_type"] == "internal"
        assert r["error_code"] == "0"
        assert r["error_name"] == "TimeoutError"
        assert r["error.type"] == "TimeoutError"
        assert r["http.status_code"] == "0"

    def test_timeout_branch_via_exc_name(self) -> None:
        """Timeout in exc_name (case insensitive) + non-zero code -> timeout."""
        r = classify_error("ConnectionTimeout", status_code=408)
        assert r["error.category"] == "timeout"
        assert r["error.severity"] == "info"
        assert r["error_type"] == "internal"

    def test_timeout_branch_via_lowercase_timeout(self) -> None:
        """Lower case 'timeout' in exc_name still triggers timeout branch."""
        r = classify_error("read_timeout_error", status_code=408)
        assert r["error.category"] == "timeout"

    def test_server_error_branch_all_values(self) -> None:
        """status_code=500, no timeout in name."""
        r = classify_error("InternalServerError", status_code=500)
        assert r["error.category"] == "server_error"
        assert r["error.severity"] == "critical"
        assert r["error_type"] == "server"
        assert r["error_code"] == "500"
        assert r["error_name"] == "InternalServerError"
        assert r["error.type"] == "InternalServerError"
        assert r["http.status_code"] == "500"

    def test_server_error_at_502(self) -> None:
        r = classify_error("BadGateway", status_code=502)
        assert r["error.category"] == "server_error"
        assert r["error.severity"] == "critical"
        assert r["error_type"] == "server"

    def test_client_error_branch_all_values_non_429(self) -> None:
        """status_code=400, non-429 -> client_error with severity=warning."""
        r = classify_error("BadRequest", status_code=400)
        assert r["error.category"] == "client_error"
        assert r["error.severity"] == "warning"
        assert r["error_type"] == "client"
        assert r["error_code"] == "400"
        assert r["error_name"] == "BadRequest"
        assert r["error.type"] == "BadRequest"
        assert r["http.status_code"] == "400"

    def test_client_error_429_severity_is_critical(self) -> None:
        """Kills: code == 429 boundary; severity must be 'critical' for 429."""
        r = classify_error("TooManyRequests", status_code=429)
        assert r["error.category"] == "client_error"
        assert r["error.severity"] == "critical"
        assert r["error_type"] == "client"
        assert r["error_code"] == "429"

    def test_client_error_428_severity_is_warning(self) -> None:
        """Boundary: 428 is NOT 429, severity must be 'warning'."""
        r = classify_error("PreconditionRequired", status_code=428)
        assert r["error.category"] == "client_error"
        assert r["error.severity"] == "warning"

    def test_client_error_430_severity_is_warning(self) -> None:
        """Boundary: 430 is NOT 429, severity must be 'warning'."""
        r = classify_error("SomeClientError", status_code=430)
        assert r["error.category"] == "client_error"
        assert r["error.severity"] == "warning"

    def test_unclassified_branch_all_values(self) -> None:
        """status_code=200 (below 400, non-zero) -> unclassified."""
        r = classify_error("OK", status_code=200)
        assert r["error.category"] == "unclassified"
        assert r["error.severity"] == "info"
        assert r["error_type"] == "internal"
        assert r["error_code"] == "200"
        assert r["error_name"] == "OK"
        assert r["error.type"] == "OK"
        assert r["http.status_code"] == "200"

    def test_unclassified_at_399(self) -> None:
        """Boundary: 399 is below 400, must be unclassified."""
        r = classify_error("Redirect", status_code=399)
        assert r["error.category"] == "unclassified"
        assert r["error.severity"] == "info"
        assert r["error_type"] == "internal"

    def test_status_code_none_defaults_to_0(self) -> None:
        """Kills: status_code is not None else 0 mutation."""
        r = classify_error("Error", status_code=None)
        assert r["error_code"] == "0"
        assert r["http.status_code"] == "0"
        # code=0 with no timeout in name -> unclassified (not timeout)
        assert r["error.category"] == "unclassified"

    def test_status_code_none_no_timeout_in_name(self) -> None:
        """Without timeout in name and no timeout status code, code=0 -> unclassified."""
        r = classify_error("ValueError")
        assert r["error.category"] == "unclassified"

    def test_status_code_zero_no_timeout_in_name(self) -> None:
        """status_code=0 with no timeout name should be unclassified."""
        r = classify_error("SomeError", status_code=0)
        assert r["error.category"] == "unclassified"
        assert r["error.severity"] == "info"
        assert r["error_type"] == "internal"

    def test_server_error_at_499_is_client_not_server(self) -> None:
        """Boundary: 499 >= 400 but < 500, should be client_error."""
        r = classify_error("ClientError", status_code=499)
        assert r["error.category"] == "client_error"
        assert r["error_type"] == "client"

    def test_server_error_at_501(self) -> None:
        """501 is >= 500, server_error."""
        r = classify_error("NotImplemented", status_code=501)
        assert r["error.category"] == "server_error"

    def test_timeout_in_name_overrides_server_status(self) -> None:
        """'timeout' in name triggers timeout even with 500+ status."""
        r = classify_error("GatewayTimeout", status_code=504)
        assert r["error.category"] == "timeout"

    def test_timeout_in_name_overrides_client_status(self) -> None:
        """'timeout' in name triggers timeout even with 400 status."""
        r = classify_error("RequestTimeout", status_code=408)
        assert r["error.category"] == "timeout"


class TestClassifyErrorStringLiterals:
    """Verify that specific string literal values cannot be swapped."""

    def test_category_timeout_exact(self) -> None:
        r = classify_error("TimeoutError", status_code=None)
        assert r["error.category"] == "timeout"
        assert r["error.category"] != "server_error"
        assert r["error.category"] != "client_error"
        assert r["error.category"] != "unclassified"

    def test_category_server_error_exact(self) -> None:
        r = classify_error("E", status_code=500)
        assert r["error.category"] == "server_error"
        assert r["error.category"] != "timeout"
        assert r["error.category"] != "client_error"

    def test_category_client_error_exact(self) -> None:
        r = classify_error("E", status_code=400)
        assert r["error.category"] == "client_error"
        assert r["error.category"] != "server_error"
        assert r["error.category"] != "timeout"

    def test_category_unclassified_exact(self) -> None:
        r = classify_error("E", status_code=200)
        assert r["error.category"] == "unclassified"
        assert r["error.category"] != "timeout"
        assert r["error.category"] != "client_error"

    def test_severity_info_in_timeout(self) -> None:
        r = classify_error("TimeoutError", status_code=None)
        assert r["error.severity"] == "info"
        assert r["error.severity"] != "critical"
        assert r["error.severity"] != "warning"

    def test_severity_critical_in_server(self) -> None:
        r = classify_error("E", status_code=500)
        assert r["error.severity"] == "critical"
        assert r["error.severity"] != "info"
        assert r["error.severity"] != "warning"

    def test_severity_warning_in_client(self) -> None:
        r = classify_error("E", status_code=401)
        assert r["error.severity"] == "warning"
        assert r["error.severity"] != "critical"
        assert r["error.severity"] != "info"

    def test_error_type_internal_in_timeout(self) -> None:
        r = classify_error("TimeoutError", status_code=None)
        assert r["error_type"] == "internal"
        assert r["error_type"] != "server"
        assert r["error_type"] != "client"

    def test_error_type_server_in_server_branch(self) -> None:
        r = classify_error("E", status_code=500)
        assert r["error_type"] == "server"
        assert r["error_type"] != "internal"
        assert r["error_type"] != "client"

    def test_error_type_client_in_client_branch(self) -> None:
        r = classify_error("E", status_code=400)
        assert r["error_type"] == "client"
        assert r["error_type"] != "server"
        assert r["error_type"] != "internal"

    def test_error_type_internal_in_unclassified(self) -> None:
        r = classify_error("E", status_code=200)
        assert r["error_type"] == "internal"

    def test_severity_info_in_unclassified(self) -> None:
        r = classify_error("E", status_code=200)
        assert r["error.severity"] == "info"


class TestClassifyErrorTimeoutStatusCodes:
    """Verify that HTTP 408/504 are classified as timeout regardless of exc_name."""

    def test_408_is_timeout(self) -> None:
        """HTTP 408 Request Timeout must be classified as timeout."""
        r = classify_error("SomeError", status_code=408)
        assert r["error.category"] == "timeout"
        assert r["error.severity"] == "info"
        assert r["error_type"] == "internal"

    def test_504_is_timeout(self) -> None:
        """HTTP 504 Gateway Timeout must be classified as timeout."""
        r = classify_error("SomeError", status_code=504)
        assert r["error.category"] == "timeout"
        assert r["error.severity"] == "info"
        assert r["error_type"] == "internal"

    def test_status_code_none_non_timeout_name_is_unclassified(self) -> None:
        """status_code=None with non-timeout exc_name -> unclassified (code=0)."""
        r = classify_error("RuntimeError", status_code=None)
        assert r["error.category"] == "unclassified"
        assert r["error_code"] == "0"

    def test_status_code_zero_non_timeout_name_is_unclassified(self) -> None:
        """status_code=0 with non-timeout exc_name -> unclassified."""
        r = classify_error("RuntimeError", status_code=0)
        assert r["error.category"] == "unclassified"

    def test_timeout_name_with_408_is_timeout(self) -> None:
        """exc_name contains 'timeout' AND status_code=408 -> still timeout."""
        r = classify_error("RequestTimeout", status_code=408)
        assert r["error.category"] == "timeout"

    def test_timeout_name_with_none_status_is_timeout(self) -> None:
        """exc_name contains 'timeout' with status_code=None -> timeout."""
        r = classify_error("NetworkTimeout", status_code=None)
        assert r["error.category"] == "timeout"
        assert r["error_code"] == "0"

    def test_407_is_not_timeout(self) -> None:
        """HTTP 407 is not a timeout code; no 'timeout' in name -> client_error."""
        r = classify_error("SomeError", status_code=407)
        assert r["error.category"] == "client_error"

    def test_503_is_not_timeout(self) -> None:
        """HTTP 503 (non-504) without timeout name -> server_error."""
        r = classify_error("ServiceUnavailable", status_code=503)
        assert r["error.category"] == "server_error"


class TestClassifyErrorDictKeys:
    """Verify all expected dict keys are present and correctly named."""

    def test_all_keys_present(self) -> None:
        r = classify_error("E", status_code=500)
        expected_keys = {
            "error_type",
            "error_code",
            "error_name",
            "error.type",
            "error.category",
            "error.severity",
            "http.status_code",
        }
        assert set(r.keys()) == expected_keys

    def test_error_dot_type_matches_exc_name(self) -> None:
        """Kills: error.type key mapping to exc_name."""
        r = classify_error("SpecificExcName", status_code=500)
        assert r["error.type"] == "SpecificExcName"

    def test_http_status_code_is_string_of_code(self) -> None:
        """Kills: http.status_code key mapping."""
        r = classify_error("E", status_code=503)
        assert r["http.status_code"] == "503"
        assert isinstance(r["http.status_code"], str)
