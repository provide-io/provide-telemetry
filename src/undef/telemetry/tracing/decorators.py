# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
"""Tracing decorators."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, cast

from undef.telemetry.tracing.provider import get_tracer

P = ParamSpec("P")
R = TypeVar("R")


def trace(name: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        span_name = name or getattr(fn, "__name__", fn.__class__.__name__)

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                with get_tracer(fn.__module__).start_as_current_span(span_name):
                    return await fn(*args, **kwargs)

            return cast(Callable[P, R], async_wrapper)  # pragma: no mutate

        @functools.wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with get_tracer(fn.__module__).start_as_current_span(span_name):
                return fn(*args, **kwargs)

        return cast(Callable[P, R], sync_wrapper)  # pragma: no mutate

    return decorator
