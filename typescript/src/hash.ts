// SPDX-FileCopyrightText: Copyright (c) 2025-2026 provide.io llc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

const INITIAL_HASH: number[] = [
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
];

const ROUND_CONSTANTS: number[] = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

function add32(...values: number[]): number {
  let sum = 0;
  for (const value of values) {
    sum = (sum + (value >>> 0)) >>> 0;
  }
  return sum;
}

function rotateRight(value: number, bits: number): number {
  return (value >>> bits) | (value << (32 - bits));
}

function sha256Words(bytes: Uint8Array): number[] {
  const bitLength = bytes.length * 8;
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;

  const view = new DataView(padded.buffer);
  // Stryker disable next-line ArithmeticOperator: highBits is always 0 for inputs under 512 MB — division vs multiplication both produce 0 after ToUint32 coercion
  const highBits = Math.floor(bitLength / 0x100000000);
  const lowBits = bitLength >>> 0;
  // Stryker disable next-line BooleanLiteral: highBits is 0 for all testable inputs — big-endian vs little-endian of 0 is identical
  view.setUint32(paddedLength - 8, highBits, false);
  view.setUint32(paddedLength - 4, lowBits, false);

  const words = new Uint32Array(64);
  let [h0, h1, h2, h3, h4, h5, h6, h7] = INITIAL_HASH;

  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let i = 0; i < 16; i++) {
      words[i] = view.getUint32(offset + i * 4, false);
    }

    // Not a C-style for loop: Stryker's UpdateOperator mutator turns `i++`
    // into `i--`, producing an infinite loop that is only ever observable as
    // a test timeout, never a killed mutant. Iterating a pre-built index
    // array (16..63, a fixed SHA-256 constant range) removes the increment
    // operator entirely. sha256Hex's known-vector tests in hash.test.ts
    // still pin correctness.
    // Stryker disable next-line EqualityOperator: Uint32Array(64) silently ignores writes to index 64 — the extra iteration is a no-op
    for (const i of Array.from({ length: 48 }, (_, idx) => idx + 16)) {
      const w15 = words[i - 15] as number;
      const w2 = words[i - 2] as number;
      const sigma0 = rotateRight(w15, 7) ^ rotateRight(w15, 18) ^ (w15 >>> 3);
      const sigma1 = rotateRight(w2, 17) ^ rotateRight(w2, 19) ^ (w2 >>> 10);
      words[i] = add32(words[i - 16] as number, sigma0, words[i - 7] as number, sigma1);
    }

    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;

    // Same rationale as the message-schedule loop above: a fixed 0..63 range,
    // rewritten to avoid the UpdateOperator mutator's infinite-loop escape.
    for (const i of Array.from({ length: 64 }, (_, idx) => idx)) {
      const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choose = (e & f) ^ (~e & g);
      const temp1 = add32(h, sum1, choose, ROUND_CONSTANTS[i] as number, words[i] as number);
      const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = add32(sum0, majority);

      h = g;
      g = f;
      f = e;
      e = add32(d, temp1);
      d = c;
      c = b;
      b = a;
      a = add32(temp1, temp2);
    }

    h0 = add32(h0, a);
    h1 = add32(h1, b);
    h2 = add32(h2, c);
    h3 = add32(h3, d);
    h4 = add32(h4, e);
    h5 = add32(h5, f);
    h6 = add32(h6, g);
    h7 = add32(h7, h);
  }

  return [h0, h1, h2, h3, h4, h5, h6, h7];
}

function wordsToHex(words: number[]): string {
  return words.map((word) => word.toString(16).padStart(8, '0')).join('');
}

function wordsToBytes(words: number[]): Uint8Array {
  const out = new Uint8Array(words.length * 4);
  const view = new DataView(out.buffer);
  words.forEach((word, i) => {
    view.setUint32(i * 4, word, false);
  });
  return out;
}

export function sha256Hex(input: string): string {
  return wordsToHex(sha256Words(new TextEncoder().encode(input)));
}

/** SHA-256 over raw bytes, returning the 32-byte digest. */
export function sha256Bytes(bytes: Uint8Array): Uint8Array {
  return wordsToBytes(sha256Words(bytes));
}

/** SHA-256 block size in bytes — the key-padding width HMAC (RFC 2104) requires. */
const HMAC_BLOCK_SIZE = 64;
const HMAC_INNER_PAD = 0x36;
const HMAC_OUTER_PAD = 0x5c;

/**
 * Real HMAC-SHA256 (RFC 2104), returned as lowercase hex.
 *
 * The receipt signature this produces is cross-checked against
 * `spec/receipt_fixtures.yaml`, whose vectors come from Python's `hmac` module
 * — so this is the same construction every other SDK signs with, not a
 * look-alike. Its predecessor here hashed `sha256(key + "|" + payload)`, which
 * is a keyed digest, not an HMAC: length-extendable, and unable to reproduce
 * any cross-language vector.
 *
 * Kept as pure JavaScript on top of the SHA-256 above rather than routed
 * through WebCrypto, because `crypto.subtle.sign` is async and only available
 * over HTTPS/localhost in browsers, while the redaction hook this serves is
 * synchronous and must work in every runtime the package ships to.
 */
export function hmacSha256Hex(key: Uint8Array, message: Uint8Array): string {
  const block = new Uint8Array(HMAC_BLOCK_SIZE);
  // A key longer than the block is hashed down first; anything shorter is
  // zero-padded, which the freshly allocated array already is.
  block.set(key.length > HMAC_BLOCK_SIZE ? sha256Bytes(key) : key);

  const inner = new Uint8Array(HMAC_BLOCK_SIZE + message.length);
  const outer = new Uint8Array(HMAC_BLOCK_SIZE + 32);
  // Iterating `block` rather than a counted loop: `i < HMAC_BLOCK_SIZE` has an
  // off-by-one mutant that is genuinely equivalent here, because the two
  // `.set` calls below overwrite index 64 anyway. Driving the loop from the
  // array removes the comparison instead of arguing about it — the same
  // rationale as the message-schedule loops above.
  block.forEach((byte, i) => {
    inner[i] = byte ^ HMAC_INNER_PAD;
    outer[i] = byte ^ HMAC_OUTER_PAD;
  });
  inner.set(message, HMAC_BLOCK_SIZE);
  outer.set(sha256Bytes(inner), HMAC_BLOCK_SIZE);
  return wordsToHex(sha256Words(outer));
}

export function shortHash12(input: string): string {
  return sha256Hex(input).slice(0, 12);
}

/**
 * Generate `numBytes` random bytes and return them as a lowercase hex string.
 * Uses the Web Crypto API (available in Node.js 15+, browsers, and edge runtimes).
 */
export function randomHex(numBytes: number): string {
  const bytes = new Uint8Array(numBytes);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}
