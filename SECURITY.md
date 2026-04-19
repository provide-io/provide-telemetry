# Security Policy

## Supported Versions

| Version | Supported        |
| ------- | ---------------- |
| 0.4.x   | Yes              |
| 0.3.x   | No (end-of-life) |
| < 0.3   | No               |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report security issues via [GitHub private vulnerability reporting](https://github.com/provide-io/provide-telemetry/security/advisories/new).

Include:

- A description of the vulnerability and its potential impact
- Steps to reproduce or a minimal proof-of-concept
- The version(s) affected
- Any suggested mitigations you are aware of

You will receive an acknowledgement within 72 hours. We aim to ship a fix within 14 days of confirmation.

## Scope

This policy covers:

- `provide-telemetry` (PyPI) — `src/provide/telemetry/`
- `@provide-io/telemetry` (npm) — `typescript/src/`

Out of scope: third-party dependencies (report directly to their maintainers), example scripts, test fixtures.

## OTel Dependency Versions

Pin OpenTelemetry packages with **caret ranges** (e.g. `^1.27.0`). Run the full test suite on every minor version bump before merging. Breaking changes in OTel SDKs should be caught by CI before release.

## PII and Secret Detection

Both language implementations include built-in sanitization:

- Default fields (`password`, `token`, `secret`, `authorization`, `api_key`) are redacted automatically.
- The PII rule engine supports custom rules with nested object traversal.
- Secret pattern scanning detects high-entropy strings and known credential formats in attribute values.

## Configuration Hardening

Production deployments should enable these config options:

| Option                       | Effect                                                             |
| ---------------------------- | ------------------------------------------------------------------ |
| `strictSchema`               | Rejects log events that do not match the registered event schema   |
| `logSanitize`                | Enables PII redaction in the structlog/pino processor chain        |
| `securityMaxAttrValueLength` | Truncates attribute values to prevent log injection / exfiltration |
| `securityMaxAttrCount`       | Caps the number of attributes per event to limit cardinality abuse |

## Credential Management

- Use `admin@provide.test` for all local development and test fixtures.
- Never commit real credentials, tokens, or API keys. Use environment variables or secret managers.
- CI secrets are managed via GitHub Actions encrypted secrets.

## Supply Chain

- An SBOM (Software Bill of Materials) is generated for each release.
- Dependabot is enabled for all language directories and GitHub Actions workflows.
- SPDX license headers (Apache-2.0) are enforced on every source file via CI.
