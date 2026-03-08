# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.

from __future__ import annotations

from urllib.parse import quote

from hypothesis import given
from hypothesis import strategies as st

from undef.telemetry.config import _parse_bool, _parse_otlp_headers


def _encode_headers(headers: dict[str, str]) -> str:
    return ",".join(f"{k}={quote(v, safe='')}" for k, v in headers.items())


@given(
    default=st.booleans(),
    flag=st.sampled_from(["1", "true", "TRUE", "yes", "on", "0", "false", "off", "no"]),
)
def test_parse_bool_matches_contract(default: bool, flag: str) -> None:
    expected = flag.strip().lower() in {"1", "true", "yes", "on"}
    assert _parse_bool(flag, default) is expected


@given(
    headers=st.dictionaries(
        keys=st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=8),
        values=st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), max_size=16),
        max_size=5,
    )
)
def test_parse_otlp_headers_roundtrip(headers: dict[str, str]) -> None:
    encoded = _encode_headers(headers)
    assert _parse_otlp_headers(encoded) == headers
