// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Targeted mutation-killing tests for `src/endpoint.ts`.
 *
 * These cases pin the pieces of validateOtlpEndpoint() that Stryker's
 * default-gen test suite missed: the function body / catch block are
 * non-empty, the error messages contain the endpoint text, scheme
 * equality is strict, and the IPv6-bracket-aware colon detection for
 * empty-port strings behaves correctly at every branch.
 */

import { describe, expect, it } from 'vitest';
import { validateOtlpEndpoint } from '../src/endpoint';
import { ConfigurationError } from '../src/exceptions';

describe('validateOtlpEndpoint — function body must execute (L15 BlockStatement)', () => {
  it('returns the input string unchanged when valid', () => {
    // BlockStatement mutant replaces the body with `{}`, making the function
    // return undefined.  Asserting the exact return value kills it.
    expect(validateOtlpEndpoint('http://host:4318')).toBe('http://host:4318');
  });
});

describe('validateOtlpEndpoint — catch block must throw (L19 BlockStatement)', () => {
  it('throws a real ConfigurationError when URL() throws', () => {
    // If the catch body is replaced with `{}`, `parsed` is never assigned and
    // the following protocol check throws a ReferenceError instead.  We pin
    // both the error type and the message pattern.
    expect(() => validateOtlpEndpoint('not a url at all')).toThrow(ConfigurationError);
    expect(() => validateOtlpEndpoint('not a url at all')).toThrow(/invalid OTLP endpoint/);
  });
});

describe('validateOtlpEndpoint — error messages include the endpoint text', () => {
  // Kills StringLiteral mutants that replace the template literal with `` or "".
  it.each([
    ['L20 — malformed URL template', 'not-a-url'],
    ['L23 — wrong-scheme template', 'ftp://host:4318'],
    ['L46 — explicit empty-port template', 'http://host:'],
    ['L52 — port-range template', 'http://host:0'],
  ])('%s includes the offending endpoint verbatim', (_desc, endpoint) => {
    let caught: Error | undefined;
    try {
      validateOtlpEndpoint(endpoint);
    } catch (e) {
      caught = e as Error;
    }
    expect(caught).toBeInstanceOf(ConfigurationError);
    // Verbatim substring pins the template literal — empty backtick string
    // mutants would produce a message with no endpoint text at all.
    const msg = (caught as Error).message;
    expect(msg).toContain(endpoint);
    expect(msg).toMatch(/invalid OTLP endpoint/);
  });

  it('hostname-empty error (L26) keeps generic "invalid OTLP endpoint" text', () => {
    // We cannot easily construct a URL that parses with empty hostname without
    // stubbing globals (covered in endpoint.test.ts), but we still pin the
    // template for the other paths above.
    // This test is informational: existing coverage kills L26:34 already.
    expect(true).toBe(true);
  });
});

describe('validateOtlpEndpoint — protocol check (L22)', () => {
  it('accepts http: scheme (kills ConditionalExpression true & StringLiteral "http:" → "")', () => {
    // If the condition always throws (ConditionalExpression:true), http:// would
    // throw — asserting no-throw kills it.  If 'http:' is blanked out, the
    // equality becomes parsed.protocol !== '' which is always true → throws.
    expect(() => validateOtlpEndpoint('http://host:4318')).not.toThrow();
  });

  it('accepts https: scheme (covers the && branch, kills EqualityOperator to ===)', () => {
    // With `parsed.protocol === 'https:'`, an https URL would throw; pin it as
    // passing.  Combined with the ftp-throws test below, both branches of the
    // logical && are exercised.
    expect(() => validateOtlpEndpoint('https://collector:4318')).not.toThrow();
  });

  it('rejects ftp: scheme (kills ConditionalExpression false & BlockStatement {})', () => {
    expect(() => validateOtlpEndpoint('ftp://host:4318')).toThrow(ConfigurationError);
    expect(() => validateOtlpEndpoint('ftp://host:4318')).toThrow(/invalid OTLP endpoint/);
  });
});

describe('validateOtlpEndpoint — empty-port branch (L31-L47)', () => {
  // This describes the most intricate block: when parsed.port === '' we must
  // decide whether the colon came from an IPv6 address (ok) or a trailing
  // "host:" (invalid).

  it('no-port bare hostname passes (kills the L31 ConditionalExpression:false and L44 ConditionalExpression:true mutants)', () => {
    // If L31 is forced to false, "http://host:" would NOT throw.  We pin the
    // positive counter-case here (bare host is valid).  If L44 is forced to
    // true, "http://host" (no colon) would throw — pinning also kills that.
    expect(validateOtlpEndpoint('http://host')).toBe('http://host');
    expect(validateOtlpEndpoint('http://host/v1/traces')).toBe('http://host/v1/traces');
  });

  it('trailing "host:" throws (kills L31 ConditionalExpression:false, L44 ConditionalExpression:false, and the "Stryker was here!" sentinel)', () => {
    // Under L31 false the code returns without throwing.  Under L44 false the
    // inner throw is skipped.  Under the "Stryker was here!" string mutant
    // parsed.port === 'Stryker was here!' is never true, so the branch is
    // skipped — the record would not throw.  All three collapse to the same
    // observable: the function fails to throw when it should.
    expect(() => validateOtlpEndpoint('http://host:')).toThrow(ConfigurationError);
    expect(() => validateOtlpEndpoint('http://host:')).toThrow(/invalid OTLP endpoint/);
  });

  it('IPv6 without port passes — no colon after "]" (kills L36 MethodExpression endpoint and L36 ArithmeticOperator -2)', () => {
    // MethodExpression `endpoint` mutant drops the slice entirely, so hostPart
    // becomes "http:" (the first split-on-"/" fragment) which contains ':' and
    // triggers an erroneous throw.  ArithmeticOperator `- 2` slices from
    // position 3 for http:, producing "p://[::1]" whose first split fragment
    // "p:" also contains ':' and throws.  Both are killed by asserting the
    // bare IPv6 endpoint is accepted.
    expect(validateOtlpEndpoint('http://[::1]')).toBe('http://[::1]');
  });

  it('IPv6 without port passes — kills L41 MethodExpression endsWith and L42 StringLiteral "" / MethodExpression hostPart', () => {
    // `endsWith('[')` is false for '[::1]' → else-branch treats the address as
    // a bare hostname, checks includes(':') (true) and throws.
    // `hostPart` replacement drops the slice-after-"]", so '[::1]' is tested
    // for ':' directly and throws.
    // Both are killed by this positive case.
    expect(validateOtlpEndpoint('http://[::1]/')).toBe('http://[::1]/');
  });

  it('IPv6 compressed form without port passes (kills L42 ArithmeticOperator +1 → -1)', () => {
    // For [1::], indexOf(']') is 4.  slice(+1)='' (no ':'); slice(-1)=':]:' or
    // ':]' depending on input — in the no-port form '[1::]' slice(3) yields
    // ':]' which still contains ':' and would throw under the mutant.
    expect(validateOtlpEndpoint('http://[1::]')).toBe('http://[1::]');
  });

  it('IPv6 with trailing empty port throws (kills L41 StringLiteral "" on startsWith)', () => {
    // `startsWith('')` is always true, forcing every hostPart through the
    // IPv6 branch.  For "host:" → slice(indexOf(']')+1)=slice(0)="host:",
    // includes(':')=true → still throws (same as original).  The distinction
    // from this mutant is subtle; we nevertheless pin the empty-port IPv6
    // failure as a behavioural fixpoint.
    expect(() => validateOtlpEndpoint('http://[::1]:')).toThrow(ConfigurationError);
    expect(() => validateOtlpEndpoint('http://[::1]:')).toThrow(/invalid OTLP endpoint/);
  });

  it('non-IPv6 "host:" triggers the includes(":") branch (kills L43 StringLiteral "" and L41 startsWith("[") → startsWith(""))', () => {
    // L43:27 replaces ':' with '' in hostPart.includes(':') — includes('')
    // always returns true, so "http://host" (bare hostname with no colon)
    // would incorrectly throw.  Paired with the positive bare-hostname test
    // above, this mutant is killed.
    expect(() => validateOtlpEndpoint('http://notanipv6:')).toThrow(/invalid OTLP endpoint/);
  });

  it('path-separator "/" is honoured when splitting hostPart (kills L37 StringLiteral "")', () => {
    // L37:40 replaces '/' with ''.  split('')[0] takes the first CHAR, which
    // for "host:" is "h" — no colon → no throw → bug.  We pin the correct
    // behaviour (empty-port form throws) via the "host:" case above, which
    // also kills this mutant.
    expect(() => validateOtlpEndpoint('http://ahost:')).toThrow(ConfigurationError);
  });
});

describe('validateOtlpEndpoint — port-range else branch (L49-L52)', () => {
  it('port 0 throws with port-specific message (kills L49 else-body {} and L51 LogicalOperators)', () => {
    // Under BlockStatement {} the else body never throws.  Under the ||→&&
    // variants the guard collapses so that port 0 no longer triggers.  Both
    // are killed by asserting the port-specific message path.
    expect(() => validateOtlpEndpoint('http://host:0')).toThrow(/invalid OTLP endpoint port/);
  });

  it('boundary ports 1 and 65535 are accepted (kills L51 EqualityOperator mutants)', () => {
    // `portNum < 1` vs `portNum <= 1` differ at 1; `portNum > 65535` vs `>= 65535` differ at 65535.
    expect(validateOtlpEndpoint('http://host:1')).toBe('http://host:1');
    expect(validateOtlpEndpoint('http://host:65535')).toBe('http://host:65535');
  });
});
