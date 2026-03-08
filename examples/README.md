# Examples

SPDX-License-Identifier: Apache-2.0  
SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC

## Telemetry

- `telemetry/01_basic_telemetry.py`
  - Local console/json logging.
  - Trace decorator usage.
  - Counter/histogram emission.

Run:

```bash
uv run --group dev --extra otel python examples/telemetry/01_basic_telemetry.py
```

## OpenObserve

- `openobserve/01_emit_all_signals.py`
  - Emits logs, traces, and metrics via OTLP HTTP exporters.
- `openobserve/02_verify_ingestion.py`
  - Captures pre/post stream document totals from OpenObserve API.
  - Fails fast if logs/traces/metrics did not increase.

Environment:

```bash
export OPENOBSERVE_URL=http://localhost:5080/api/default
export OPENOBSERVE_USER=user@example.com
export OPENOBSERVE_PASSWORD=password
```

Run:

```bash
uv run --group dev --extra otel python examples/openobserve/01_emit_all_signals.py
uv run --group dev --extra otel python examples/openobserve/02_verify_ingestion.py
```
