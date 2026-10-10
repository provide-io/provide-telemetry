// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * A throwaway PKI for the listener's TLS tests: a CA, a server certificate for
 * localhost / 127.0.0.1, and a client certificate, written as PEM files.
 *
 * Built with WebCrypto through @peculiar/x509 so it works on every CI runner
 * without an openssl binary.
 */

// @peculiar/x509 resolves its services through tsyringe, which needs the polyfill first.
import 'reflect-metadata';
import { webcrypto } from 'node:crypto';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as x509 from '@peculiar/x509';

x509.cryptoProvider.set(webcrypto as unknown as Crypto);

const ALG = { name: 'ECDSA', namedCurve: 'P-256', hash: 'SHA-256' };
const HOUR_MS = 3_600_000;

async function keyPair(): Promise<CryptoKeyPair> {
  return (await webcrypto.subtle.generateKey(ALG, true, ['sign', 'verify'])) as CryptoKeyPair;
}

async function keyPem(key: CryptoKey): Promise<string> {
  const der = Buffer.from(await webcrypto.subtle.exportKey('pkcs8', key));
  const body = der.toString('base64').replace(/(.{64})/g, '$1\n');
  return `-----BEGIN PRIVATE KEY-----\n${body}\n-----END PRIVATE KEY-----\n`;
}

/** Extended key usage OIDs, for issue(). */
export const SERVER_AUTH: string = x509.ExtendedKeyUsage.serverAuth;
export const CLIENT_AUTH: string = x509.ExtendedKeyUsage.clientAuth;

let serial = 1;

export class Pki {
  caFile = '';
  certFile = '';
  keyFile = '';
  clientCert = '';
  clientKey = '';
  private caCert!: x509.X509Certificate;
  private caKeys!: CryptoKeyPair;

  private constructor(readonly dir: string) {}

  static async create(dir = mkdtempSync(join(tmpdir(), 'pki-'))): Promise<Pki> {
    const pki = new Pki(dir);
    await pki.init();
    return pki;
  }

  private async init(): Promise<void> {
    const now = Date.now();
    this.caKeys = await keyPair();
    this.caCert = await x509.X509CertificateGenerator.createSelfSigned({
      serialNumber: (serial++).toString(16).padStart(2, '0'),
      name: 'CN=test CA',
      notBefore: new Date(now - HOUR_MS),
      notAfter: new Date(now + HOUR_MS),
      keys: this.caKeys,
      signingAlgorithm: ALG,
      extensions: [
        new x509.BasicConstraintsExtension(true, undefined, true),
        new x509.KeyUsagesExtension(
          x509.KeyUsageFlags.keyCertSign | x509.KeyUsageFlags.cRLSign,
          true,
        ),
        await x509.SubjectKeyIdentifierExtension.create(this.caKeys.publicKey),
      ],
    });
    this.caFile = this.write('ca.crt', this.caCert.toString('pem'));
    [this.certFile, this.keyFile] = await this.issue('server', x509.ExtendedKeyUsage.serverAuth);
    [this.clientCert, this.clientKey] = await this.issue(
      'client',
      x509.ExtendedKeyUsage.clientAuth,
    );
  }

  write(name: string, data: string): string {
    const path = join(this.dir, name);
    writeFileSync(path, data);
    return path;
  }

  /** Issue a leaf certificate signed by this CA; returns [certFile, keyFile]. */
  async issue(name: string, usage: string): Promise<[string, string]> {
    const now = Date.now();
    const keys = await keyPair();
    const cert = await x509.X509CertificateGenerator.create({
      serialNumber: (serial++).toString(16).padStart(2, '0'),
      subject: `CN=${name}`,
      issuer: this.caCert.subject,
      notBefore: new Date(now - HOUR_MS),
      notAfter: new Date(now + HOUR_MS),
      signingKey: this.caKeys.privateKey,
      publicKey: keys.publicKey,
      signingAlgorithm: ALG,
      extensions: [
        new x509.BasicConstraintsExtension(false, undefined, true),
        new x509.ExtendedKeyUsageExtension([usage]),
        new x509.SubjectAlternativeNameExtension([
          { type: 'dns', value: 'localhost' },
          { type: 'ip', value: '127.0.0.1' },
        ]),
        await x509.AuthorityKeyIdentifierExtension.create(this.caCert),
      ],
    });
    return [
      this.write(`${name}.crt`, cert.toString('pem')),
      this.write(`${name}.key`, await keyPem(keys.privateKey)),
    ];
  }
}
