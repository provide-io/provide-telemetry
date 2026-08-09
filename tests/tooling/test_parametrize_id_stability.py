# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Node ids must not change when the suite is collected twice in one process.

The mutation gate depends on this. mutmut calls ``pytest.main()`` many times in
a single interpreter: once to collect per-test timings, once for the clean run,
and once per mutant. It records node ids during the first collection and replays
them as command-line arguments on every later call.

pytest escapes a parametrize id (control characters, backslashes, non-ASCII) and
stores the escaped string back on the mark, so the *second* collection escapes
the already-escaped string again — ``[host\\nX]`` becomes ``[host\\\\nX]`` and
stays there. The replayed id then matches nothing, pytest raises ``UsageError``
and exits 4, and mutmut's ``execute_pytest`` turns that into an uncaught
``BadTestExecutionCommandsException`` inside the forked child. The child dies
nonzero, which is exactly how mutmut records "the tests detected this mutant" —
so the mutant is scored as killed without a single test having run. Two
parametrize ids did this to 110 of 4767 mutants.

Nothing in a single-collection run can see this, which is why the check lives
here and collects twice on purpose.
"""

from __future__ import annotations

import json
import subprocess  # nosec
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Collect twice inside one interpreter, exactly as mutmut does, and report the
# node ids that differ between the two passes.
_COLLECT_TWICE = textwrap.dedent(
    """
    import json
    import sys

    import pytest


    class _Recorder:
        def __init__(self):
            self.ids = []

        def pytest_collection_modifyitems(self, items):
            self.ids = [item.nodeid for item in items]


    args = [
        "--collect-only",
        "-q",
        "-p",
        "no:randomly",
        "-p",
        "no:random-order",
        "-o",
        "addopts=",
        "--no-cov",
        "tests",
    ]
    passes = []
    for _ in range(2):
        recorder = _Recorder()
        pytest.main(args, plugins=[recorder])
        passes.append(recorder.ids)

    first, second = passes
    unstable = [[a, b] for a, b in zip(first, second) if a != b]
    with open(sys.argv[1], "w", encoding="utf-8") as handle:
        json.dump({"counts": [len(first), len(second)], "unstable": unstable}, handle)
    """
)


def test_node_ids_survive_a_second_collection(tmp_path: Path) -> None:
    report = tmp_path / "unstable.json"
    completed = subprocess.run(  # nosec
        [sys.executable, "-c", _COLLECT_TWICE, str(report)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert report.exists(), f"double collection did not finish:\n{completed.stdout}\n{completed.stderr}"

    payload = json.loads(report.read_text(encoding="utf-8"))
    first_count, second_count = payload["counts"]
    assert first_count > 0, "collected nothing — the check would pass vacuously"
    assert first_count == second_count, "the second collection found a different number of tests"
    assert payload["unstable"] == [], (
        "these node ids change on a second in-process collection, which makes mutmut "
        "score mutants as killed without running their tests — give the parametrize "
        "case an explicit id with no control character, backslash or non-ASCII "
        f"character:\n{json.dumps(payload['unstable'], indent=2)}"
    )
