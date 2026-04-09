# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Attribute cardinality guardrails."""

from __future__ import annotations

__all__ = [
    "OVERFLOW_VALUE",
    "CardinalityLimit",
    "clear_cardinality_limits",
    "get_cardinality_limits",
    "guard_attributes",
    "register_cardinality_limit",
]

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CardinalityLimit:
    max_values: int
    ttl_seconds: float = 300.0


_lock = threading.Lock()
_limits: dict[str, CardinalityLimit] = {}
_seen: dict[str, dict[str, float]] = {}
_last_prune: dict[str, float] = {}
_PRUNE_INTERVAL = 5.0  # seconds between prune sweeps per key
OVERFLOW_VALUE = "__overflow__"


def register_cardinality_limit(key: str, max_values: int, ttl_seconds: float = 300.0) -> None:  # pragma: no mutate
    with _lock:
        _limits[key] = CardinalityLimit(max_values=max(1, max_values), ttl_seconds=max(1.0, ttl_seconds))
        _seen.setdefault(key, {})


def get_cardinality_limits() -> dict[str, CardinalityLimit]:
    with _lock:
        return dict(_limits)


def clear_cardinality_limits() -> None:
    with _lock:
        _limits.clear()
        _seen.clear()
        _last_prune.clear()


def _prune_expired(key: str, now: float) -> None:
    """Prune expired entries for key in-place. Caller must hold _lock."""
    limit = _limits.get(key)
    seen = _seen.get(key)
    if limit is None or seen is None:
        return
    threshold = now - limit.ttl_seconds
    for value, seen_at in list(seen.items()):
        if seen_at < threshold:
            del seen[value]


def _collect_expired(key: str, now: float) -> list[str]:
    """Return expired value candidates. Caller must hold _lock."""
    limit = _limits.get(key)
    seen = _seen.get(key)
    if limit is None or seen is None:
        return []
    threshold = now - limit.ttl_seconds
    return [v for v, t in seen.items() if t < threshold]


def _delete_expired(key: str, candidates: list[str], now: float) -> None:
    """Re-verify and delete expired candidates. Caller must hold _lock.

    Re-checks each candidate's timestamp — a concurrent caller may have
    refreshed the entry between the snapshot (Phase 1) and this deletion
    (Phase 2), in which case the entry is left intact.
    """
    limit = _limits.get(key)
    seen = _seen.get(key)
    if limit is None or seen is None:
        return
    threshold = now - limit.ttl_seconds
    for v in candidates:
        entry_time = seen.get(v)
        if entry_time is not None and entry_time < threshold:
            del seen[v]


def guard_attributes(attributes: dict[str, str]) -> dict[str, str]:
    """Guard attribute cardinality, releasing the lock between prune phases.

    Per-key locking pattern:
      Phase 0 — under lock: early exit if no limits registered.
      Phase 1 — under lock: snapshot expired candidates and update prune timer.
      (lock released between phases so concurrent callers can refresh timestamps)
      Phase 2 — under lock: re-verify and delete candidates that are still expired.
      Phase 3 — under lock: record the current value into the seen map.
    """
    now = time.monotonic()
    with _lock:
        if not _limits:
            return attributes
    guarded = dict(attributes)
    for key, value in list(guarded.items()):
        expired: list[str] = []
        with _lock:
            if _limits.get(key) is None:
                continue
            if now - _last_prune.get(key, 0.0) >= _PRUNE_INTERVAL:  # pragma: no mutate
                expired = _collect_expired(key, now)
                _last_prune[key] = now  # pragma: no mutate
        if expired:
            with _lock:
                _delete_expired(key, expired, now)
        with _lock:
            seen = _seen.setdefault(key, {})
            limit = _limits.get(key)
            if limit is None:
                continue
            if value in seen:
                seen[value] = now  # pragma: no mutate
                continue
            if len(seen) >= limit.max_values:
                guarded[key] = OVERFLOW_VALUE
                continue
            seen[value] = now  # pragma: no mutate
    return guarded
