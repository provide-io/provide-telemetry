# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""The Hypothesis deadline stays off for this suite.

`tests/conftest.py` registers a profile with `deadline=None`. Without it every
property test carries Hypothesis's 200ms per-example deadline, which this suite
is never in a position to satisfy honestly: the normal gate runs under coverage
and the mutation gate runs under mutmut's trampoline, so a slow example measures
the instrumentation.

That deadline cost a real debugging session. The mutation gate failed once on a
property that cannot fail on any input its strategy generates, left no
falsifying example to look at, and did not reproduce in seven full-suite runs —
because `DeadlineExceeded` reports a valid example and reads exactly like a
logic failure.

The guard is here rather than in a comment because the failure it prevents is
rare, remote, and expensive to diagnose from the summary line CI prints.
"""

from __future__ import annotations

import hypothesis
from hypothesis import given, settings
from hypothesis import strategies as st


def test_the_profile_disables_the_deadline() -> None:
    default = hypothesis.settings.default
    assert default is not None, "no Hypothesis profile is loaded, so conftest never ran"
    assert default.deadline is None, (
        "the Hypothesis deadline is back on; a slow example under coverage or mutmut "
        "will fail a property test for a reason that has nothing to do with the property"
    )


@settings(max_examples=1)
@given(value=st.integers())
def test_a_local_settings_decorator_inherits_the_disabled_deadline(value: int) -> None:
    """The property tests here all pass `@settings(max_examples=...)`.

    A `settings` decorator inherits every field it does not name from the
    profile loaded when the module is imported, so those decorators must not
    quietly reinstate the default deadline. If they did, the profile would
    protect almost none of the suite.
    """
    _ = value
    assert settings().deadline is None
