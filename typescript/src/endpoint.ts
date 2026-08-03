// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * OTLP endpoint validation — fail fast at setup instead of silent async failure.
 */

import { ConfigurationError } from './exceptions.js';

/**
 * Validate that an endpoint is a valid HTTP(S) URL with optional valid port.
 * Throws ConfigurationError for malformed endpoints.
 * Returns the endpoint unchanged if valid.
 *
 * Stryker reports the `!parsed.hostname` and port-range guards below as
 * survivors. They are not: forcing either to `false` and running the suite
 * fails it (one test and three tests respectively). Stryker lists the covering
 * tests in each mutant's `coveredBy` and reports testsCompleted > 0, so it ran
 * them and did not observe the failure — the same false negative in its
 * per-test result attribution that config-redact.ts documents for its presence
 * guards. Deliberately not suppressed: the guards are load-bearing, and a
 * suppression would hide a real regression if one ever landed here.
 */
export function validateOtlpEndpoint(endpoint: string): string {
  let parsed: URL;
  try {
    parsed = new URL(endpoint);
  } catch {
    throw new ConfigurationError(`invalid OTLP endpoint: ${JSON.stringify(endpoint)}`);
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new ConfigurationError(`invalid OTLP endpoint: ${JSON.stringify(endpoint)}`);
  }
  if (!parsed.hostname) {
    throw new ConfigurationError(`invalid OTLP endpoint: ${JSON.stringify(endpoint)}`);
  }
  // Detect explicit empty port — "http://host:" has port="" in URL spec but the
  // URL constructor does not throw. An empty port string is invalid for OTLP.
  // Port "0" also passes the URL constructor but is not a valid service port.
  if (parsed.port === '') {
    // Check if the original string has a trailing colon-port segment that parsed as empty.
    // We do this by checking whether removing the path from the URL's host reconstructs
    // an empty-port form. The simplest reliable check: if the raw endpoint (after scheme)
    // contains a colon followed only by "/" or end-of-string after the host, the port is empty.
    const afterScheme = endpoint.slice(parsed.protocol.length + 2); // strip "scheme//"
    const hostPart = afterScheme.split('/')[0]; // "host:" or "host" or "[::1]:" or "[::1]"
    // For IPv6 addresses like "[::1]", colons are inside brackets and do not
    // indicate a port segment. Only flag an empty port when the colon appears
    // after the closing bracket (IPv6) or after a bare hostname (IPv4/name).
    // Equivalent mutant note: for any hostPart with no ']' at all,
    // `.indexOf(']')` is -1, so `.slice(-1 + 1)` = `.slice(0)` is a no-op —
    // the "IPv6 branch" degenerates to exactly `hostPart.includes(':')`,
    // identical to the plain branch. A ']' appearing anywhere in hostPart
    // without a leading '[' would distinguish them, but that's unreachable:
    // hostPart comes from a URL that already parsed successfully via `new
    // URL()`, and WHATWG host parsing never produces a bare ']' outside an
    // IPv6 literal.
    // Stryker disable next-line StringLiteral
    const colonAfterHost = hostPart.startsWith('[')
      ? hostPart.slice(hostPart.indexOf(']') + 1).includes(':')
      : hostPart.includes(':');
    if (colonAfterHost) {
      // There is a colon after the hostname — port was explicitly provided but empty.
      throw new ConfigurationError(`invalid OTLP endpoint: ${JSON.stringify(endpoint)}`);
    }
    // No colon after hostname — port was simply omitted, which is fine.
  } else {
    const portNum = Number(parsed.port);
    if (!Number.isInteger(portNum) || portNum < 1 || portNum > 65535) {
      throw new ConfigurationError(`invalid OTLP endpoint port: ${JSON.stringify(endpoint)}`);
    }
  }
  return endpoint;
}
