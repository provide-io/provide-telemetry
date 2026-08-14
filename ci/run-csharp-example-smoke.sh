#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#
# Runs every standalone C# telemetry example to completion. The solution build
# already compiles them under -warnaserror; this proves they execute. The
# openobserve examples need a live backend and are excluded, matching the
# Python/TypeScript/Go smoke jobs.
set -euo pipefail

cd "$(dirname "$0")/../csharp"

for proj in examples/telemetry/*/*.csproj; do
  echo "=== ${proj}"
  dotnet run --project "$proj" -c Release --no-build
done

echo "All C# telemetry examples ran to completion."
