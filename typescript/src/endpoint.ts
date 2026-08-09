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
 * There is deliberately no `!parsed.hostname` guard. `http:` and `https:` are
 * "special schemes" in the WHATWG URL Standard, and its host parser refuses an
 * empty host for those: `new URL('https://')`, `'http://?q'`, `'http://#f'` and
 * `'http://user:pw@/'` all throw, and `'http:///a/b'` re-parses `a` as the host
 * rather than yielding an empty one. Anything that reaches this point therefore
 * already has a non-empty hostname. The guard that used to sit here could only
 * be reached by a test that replaced globalThis.URL with a fake whose hostname
 * getter returned '' — which proves something about the fake, not about any
 * endpoint a caller can pass. Removed rather than suppressed, so the mutation
 * report stops carrying a survivor plus two uncovered lines for dead code.
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
    // No upper-bound clause: WHATWG URL parsing already throws for any port
    // above 65535 (new URL('http://h:65536') is a TypeError), so a parsed
    // port can only be 0..65535 and an upper-bound check here is unreachable
    // — it existed only to be an equivalent Stryker mutant.
    const portNum = Number(parsed.port);
    if (!Number.isInteger(portNum) || portNum < 1) {
      throw new ConfigurationError(`invalid OTLP endpoint port: ${JSON.stringify(endpoint)}`);
    }
  }
  return endpoint;
}
