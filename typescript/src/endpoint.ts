// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * OTLP endpoint validation — fail fast at setup instead of silent async failure.
 */

import { ConfigurationError } from './exceptions';

/**
 * Validate that an endpoint is a valid HTTP(S) URL with optional valid port.
 * Throws ConfigurationError for malformed endpoints.
 * Returns the endpoint unchanged if valid.
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
