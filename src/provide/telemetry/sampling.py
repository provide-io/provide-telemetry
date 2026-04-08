# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Runtime sampling policy controls."""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field

from provide.telemetry.health import increment_dropped

Signal = str


@dataclass(frozen=True, slots=True)
class SamplingPolicy:
    default_rate: float = 1.0
    overrides: dict[str, float] = field(default_factory=dict)


_lock = threading.Lock()
_policies: dict[Signal, SamplingPolicy] = {
    "logs": SamplingPolicy(),
    "traces": SamplingPolicy(),
    "metrics": SamplingPolicy(),
}


def _normalize_rate(rate: float) -> float:
    clamped = max(0.0, min(1.0, rate))
    if clamped != rate:
        _logger.warning("sampling.rate.clamped.warning")  # pragma: no mutate
    return clamped


def set_sampling_policy(signal: Signal, policy: SamplingPolicy) -> None:
    sig = signal if signal in _policies else "logs"
    normalized = SamplingPolicy(
        default_rate=_normalize_rate(policy.default_rate),
        overrides={k: _normalize_rate(v) for k, v in policy.overrides.items()},
    )
    with _lock:
        _policies[sig] = normalized


def get_sampling_policy(signal: Signal) -> SamplingPolicy:
    sig = signal if signal in _policies else "logs"
    with _lock:
        return _policies[sig]


def should_sample(signal: Signal, key: str | None = None) -> bool:
    sig = _validate_signal(signal)
    return _should_sample_unchecked(sig, key)


def _should_sample_unchecked(sig: Signal, key: str | None = None) -> bool:
    """Hot-path sampling check — caller must pass a validated signal."""
    # No lock needed: CPython's GIL makes dict reads atomic, and
    # SamplingPolicy is a frozen dataclass (immutable after creation).
    policy = _policies[sig]
    rate = policy.default_rate
    if key is not None and key in policy.overrides:
        rate = policy.overrides[key]
    # Fast path: rates stored via set_sampling_policy are already normalized,
    # so skip _normalize_rate and test the common 1.0/0.0 cases first.
    if rate >= 1.0:  # pragma: no mutate
        return True
    if rate <= 0.0:  # pragma: no mutate
        increment_dropped(sig)
        return False
    keep = random.random() < rate  # noqa: S311 - non-crypto telemetry sampling.
    if not keep:
        increment_dropped(sig)
    return keep


def reset_sampling_for_tests() -> None:
    with _lock:
        for signal in ("logs", "traces", "metrics"):
            _policies[signal] = SamplingPolicy()
