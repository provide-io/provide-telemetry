#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Runs every standalone Rust telemetry example to completion. Compilation is
# already proven by the coverage job's --all-targets build; this proves the
# examples actually execute — a panic, a hang, or an API drift in any of them
# fails the job. The openobserve_* and e2e_* examples need a live backend and
# are exercised by the shared E2E workflow instead.
set -euo pipefail

cd "$(dirname "$0")/../rust"

# Build once so the per-example runs are just process launches.
cargo build --locked --examples

for src in examples/telemetry_*.rs; do
  name="$(basename "$src" .rs)"
  echo "=== ${name}"
  cargo run --locked --quiet --example "$name"
done

echo "All Rust telemetry examples ran to completion."
