// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0
// @vitest-environment node

/** The listener's web config: validation, basic auth, TLS options and certificate rotation. */

import { mkdtempSync, readFileSync, utimesSync, writeFileSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import bcrypt from 'bcryptjs';
import { stringify } from 'yaml';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { must } from './support/must.js';
import {
  _setOptionalImporterForTests,
  DUMMY_HASH,
  INSTALL_HINT,
  loadWebConfig,
  stopListener,
  TlsReloader,
  WebConfigError,
  WebSecurity,
} from '../src/prom-listener.js';
import { _resetPullForTests, markPullReady } from '../src/prom-pull.js';
import { basic, fetchListener, PASSWORD, startListener } from './support/listener-client.js';
import { Pki, SERVER_AUTH } from './support/pki.js';

let pki: Pki;
let hashed: string;

beforeAll(async () => {
  pki = await Pki.create();
  hashed = bcrypt.hashSync(PASSWORD, 4);
}, 30_000);

beforeEach(() => {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  markPullReady(
    { collect: async () => ({ resourceMetrics: undefined }) },
    { strategy: 'UnderscoreEscapingWithSuffixes', scopeLabels: false, targetInfo: true },
  );
});

afterEach(async () => {
  await stopListener();
  _setOptionalImporterForTests();
  _resetPullForTests();
  vi.restoreAllMocks();
});

function writeConfig(config: unknown, dir = mkdtempSync(join(tmpdir(), 'web-'))): string {
  const text = (typeof config === 'string' ? config : stringify(config))
    .replace(/\{cert\}/g, pki.certFile)
    .replace(/\{key\}/g, pki.keyFile)
    .replace(/\{ca\}/g, pki.caFile)
    .replace(/\{missing\}/g, join(dir, 'missing.pem'))
    .replace(/\{hash\}/g, hashed);
  const path = join(dir, 'web.yml');
  writeFileSync(path, text);
  return path;
}

async function rejection(path: string): Promise<WebConfigError> {
  try {
    await loadWebConfig(path);
  } catch (err) {
    return err as WebConfigError;
  }
  throw new Error('expected loadWebConfig to reject');
}

describe('web config validation', () => {
  const TLS = { cert_file: '{cert}', key_file: '{key}' };
  it.each([
    [[1, 2], ': only basic_auth_users, tls_server_config are supported'],
    ['42', ': only basic_auth_users, tls_server_config are supported'],
    [{ http_server_config: {} }, ': only basic_auth_users, tls_server_config are supported'],
    [
      { tls_server_config: 'x' },
      'tls_server_config: only cert_file, client_auth_type, client_ca_file, key_file, min_version are supported',
    ],
    [{ tls_server_config: null }, 'tls_server_config: only'],
    [{ tls_server_config: [] }, 'tls_server_config: only'],
    [{ tls_server_config: { ...TLS, cipher_suites: [] } }, 'tls_server_config: only'],
    [
      { tls_server_config: { cert_file: '{cert}' } },
      'tls_server_config needs cert_file and key_file',
    ],
    [
      { tls_server_config: { key_file: '{key}' } },
      'tls_server_config needs cert_file and key_file',
    ],
    [
      { tls_server_config: { ...TLS, min_version: 'TLS10' } },
      'tls_server_config.min_version "TLS10": want TLS12 or TLS13',
    ],
    [{ tls_server_config: { ...TLS, min_version: 'toString' } }, 'want TLS12 or TLS13'],
    [
      { tls_server_config: { ...TLS, client_auth_type: 'Sometimes' } },
      'tls_server_config.client_auth_type "Sometimes" is not supported',
    ],
    [
      { tls_server_config: { ...TLS, client_auth_type: 'VerifyClientCertIfGiven' } },
      'tls_server_config.client_auth_type VerifyClientCertIfGiven needs client_ca_file',
    ],
    [
      { tls_server_config: { ...TLS, client_auth_type: 'RequireAndVerifyClientCert' } },
      'needs client_ca_file',
    ],
    [
      { tls_server_config: { cert_file: '{cert}', key_file: '{missing}' } },
      'tls_server_config: ENOENT',
    ],
    [{ tls_server_config: { cert_file: '{key}', key_file: '{key}' } }, 'tls_server_config: '],
    [{ tls_server_config: { ...TLS, client_ca_file: '{missing}' } }, 'tls_server_config: ENOENT'],
    [{ basic_auth_users: ['e2e'] }, ': basic_auth_users must map user names to bcrypt hashes'],
    [{ basic_auth_users: 'e2e' }, 'basic_auth_users must map user names to bcrypt hashes'],
    [{ basic_auth_users: { e2e: 'plaintext' } }, ': basic_auth_users[e2e] is not a bcrypt hash'],
  ])('rejects %j', async (config, message) => {
    const path = writeConfig(config);
    const err = await rejection(path);
    expect(err).toBeInstanceOf(WebConfigError);
    expect(err.name).toBe('WebConfigError');
    expect(err.message).toContain(message);
    if (message.startsWith(': ')) expect(err.message.startsWith(`web config ${path}: `)).toBe(true);
  });

  const VALID = '$2a$10$' + 'a'.repeat(53);
  it.each([
    [VALID, true],
    ['$2b$04$' + 'A'.repeat(53), true],
    ['$2y$31$' + './'.repeat(26) + '9', true],
    ['$2b$19$' + 'a'.repeat(53), true],
    ['$2b$20$' + 'a'.repeat(53), true],
    ['$2c$10$' + 'a'.repeat(53), false],
    ['$2$10$' + 'a'.repeat(53), false],
    ['$3a$10$' + 'a'.repeat(53), false],
    ['$2a$03$' + 'a'.repeat(53), false],
    ['$2a$32$' + 'a'.repeat(53), false],
    ['$2a$40$' + 'a'.repeat(53), false],
    ['$2a$1$' + 'a'.repeat(53), false],
    ['$2a$10$' + 'a'.repeat(52), false],
    ['$2a$10$' + 'a'.repeat(54), false],
    ['$2a$10$' + 'a'.repeat(52) + '!', false],
    ['x' + VALID, false],
    [VALID + 'x', false],
    ['$2a10$' + 'a'.repeat(54), false],
  ])('bcrypt hash format %s accepted: %s', async (hash, ok) => {
    const path = writeConfig({ basic_auth_users: { e2e: hash } });
    if (ok) await expect(loadWebConfig(path)).resolves.toBeInstanceOf(WebSecurity);
    else await expect(loadWebConfig(path)).rejects.toThrow('is not a bcrypt hash');
  });

  it('unreadable and malformed files', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'web-'));
    await expect(loadWebConfig(join(dir, 'absent.yml'))).rejects.toThrow(
      `web config ${join(dir, 'absent.yml')}: ENOENT`,
    );
    const broken = join(dir, 'broken.yml');
    writeFileSync(broken, 'tls_server_config: [unclosed\n');
    await expect(loadWebConfig(broken)).rejects.toThrow(`web config ${broken}: `);
  });

  it('an empty file, or empty users, means no security', async () => {
    for (const text of ['', '# nothing\n', 'basic_auth_users: {}\n', 'basic_auth_users:\n']) {
      const security = await loadWebConfig(writeConfig(text));
      expect(security.users.size).toBe(0);
      expect(security.tls).toBeUndefined();
      expect(await security.authorized(undefined)).toBe(true);
    }
  });

  it('relative paths resolve against the file; optional TLS settings apply', async () => {
    const path = join(pki.dir, 'relative.yml');
    writeFileSync(
      path,
      stringify({
        tls_server_config: {
          cert_file: basename(pki.certFile),
          key_file: basename(pki.keyFile),
          client_ca_file: basename(pki.caFile),
          client_auth_type: 'VerifyClientCertIfGiven',
          min_version: 'TLS13',
        },
      }),
    );
    const tls = must((await loadWebConfig(path)).tls);
    expect(tls.options.minVersion).toBe('TLSv1.3');
    expect(tls.options.ca).toEqual(readFileSync(pki.caFile));
    expect(tls.options.cert).toEqual(readFileSync(pki.certFile));
    expect(tls.options.key).toEqual(readFileSync(pki.keyFile));
    expect([tls.requestCert, tls.rejectUnauthorized]).toEqual([true, false]);
  });

  it('TLS defaults: TLS12, no client certificate, or required when a CA is named', async () => {
    const plain = must(
      (
        await loadWebConfig(
          writeConfig({ tls_server_config: { cert_file: '{cert}', key_file: '{key}' } }),
        )
      ).tls,
    );
    expect(plain.options.minVersion).toBe('TLSv1.2');
    expect(plain.options.ca).toBeUndefined();
    expect([plain.requestCert, plain.rejectUnauthorized]).toEqual([false, false]);
    const mtls = must(
      (
        await loadWebConfig(
          writeConfig({
            tls_server_config: { cert_file: '{cert}', key_file: '{key}', client_ca_file: '{ca}' },
          }),
        )
      ).tls,
    );
    expect([mtls.requestCert, mtls.rejectUnauthorized]).toEqual([true, true]);
    const none = must(
      (
        await loadWebConfig(
          writeConfig({
            tls_server_config: {
              cert_file: '{cert}',
              key_file: '{key}',
              client_ca_file: '{ca}',
              client_auth_type: 'NoClientCert',
              min_version: 'TLS12',
            },
          }),
        )
      ).tls,
    );
    expect([none.requestCert, none.rejectUnauthorized]).toEqual([false, false]);
  });

  it.each(['yaml', 'bcryptjs'])('a missing %s fails closed with the install hint', async (pkg) => {
    _setOptionalImporterForTests(async (name) => {
      if (name === pkg) throw new Error(`Cannot find package '${name}'`);
      return import(name);
    });
    const err = await rejection(writeConfig({ basic_auth_users: { e2e: '{hash}' } }));
    expect(err.message).toBe(INSTALL_HINT);
    expect(INSTALL_HINT).toContain('npm install yaml bcryptjs');
  });

  it('bcryptjs is not needed without users', async () => {
    _setOptionalImporterForTests(async (name) => {
      if (name === 'bcryptjs') throw new Error('missing');
      return import(name);
    });
    await expect(
      loadWebConfig(writeConfig({ tls_server_config: { cert_file: '{cert}', key_file: '{key}' } })),
    ).resolves.toBeInstanceOf(WebSecurity);
  });
});

describe('basic auth', () => {
  it('handles every shape of Authorization header', async () => {
    const security = await loadWebConfig(writeConfig({ basic_auth_users: { e2e: '{hash}' } }));
    expect(await new WebSecurity().authorized(undefined)).toBe(true);
    expect(await security.authorized(undefined)).toBe(false);
    expect(await security.authorized('')).toBe(false);
    expect(await security.authorized('Basic')).toBe(false);
    expect(await security.authorized('Bearer abc')).toBe(false);
    expect(await security.authorized(`Bearer ${basic('e2e', PASSWORD).slice(6)}`)).toBe(false);
    expect(await security.authorized('Basic !!!!')).toBe(false);
    expect(await security.authorized('Basic abc')).toBe(false);
    expect(await security.authorized(`Basic ${Buffer.from([0xff, 0xfe]).toString('base64')}`)).toBe(
      false,
    );
    expect(await security.authorized(`Basic ${Buffer.from('no-colon').toString('base64')}`)).toBe(
      false,
    );
    expect(await security.authorized(basic('nobody', PASSWORD))).toBe(false);
    expect(await security.authorized(basic('e2e', 'wrong'))).toBe(false);
    expect(await security.authorized(basic('e2e', `${PASSWORD}:extra`))).toBe(false);
    expect(
      await security.authorized(`basic ${Buffer.from(`e2e:${PASSWORD}`).toString('base64')}`),
    ).toBe(true);
    expect(await security.authorized(`BASIC ${basic('e2e', PASSWORD).slice(6)}`)).toBe(true);
  });

  it('a password containing a colon splits at the first one', async () => {
    const security = await loadWebConfig(
      writeConfig({ basic_auth_users: { e2e: bcrypt.hashSync('a:b', 4) } }),
    );
    expect(await security.authorized(basic('e2e', 'a:b'))).toBe(true);
  });

  it('caches successful checks only, and compares unknown users against the dummy hash', async () => {
    const compare = vi.fn(async (password: string, hash: string) => bcrypt.compare(password, hash));
    const security = new WebSecurity(new Map([['e2e', hashed]]), undefined, { compare });
    expect(await security.authenticate('e2e', 'wrong')).toBe(false);
    expect(await security.authenticate('e2e', 'wrong')).toBe(false);
    expect(compare).toHaveBeenCalledTimes(2);
    expect(await security.authenticate('e2e', PASSWORD)).toBe(true);
    expect(await security.authenticate('e2e', PASSWORD)).toBe(true);
    expect(compare).toHaveBeenCalledTimes(3);
    expect(await security.authenticate('nobody', PASSWORD)).toBe(false);
    expect(compare).toHaveBeenLastCalledWith(PASSWORD, DUMMY_HASH);
    // The cache keys on user and password together.
    expect(await security.authenticate('e2e\0x', PASSWORD)).toBe(false);
  });

  it('the dummy hash is a real cost-10 bcrypt hash', () => {
    expect(bcrypt.getRounds(DUMMY_HASH)).toBe(10);
    expect(bcrypt.compareSync('anything', DUMMY_HASH)).toBe(false);
  });
});

describe('TLS on the wire', () => {
  it('VerifyClientCertIfGiven: none is fine, a valid one is fine, a foreign one is refused', async () => {
    const foreign = await Pki.create();
    await startListener({
      prometheusWebConfig: writeConfig({
        tls_server_config: {
          cert_file: '{cert}',
          key_file: '{key}',
          client_ca_file: '{ca}',
          client_auth_type: 'VerifyClientCertIfGiven',
        },
      }),
    });
    expect((await fetchListener('https', { ca: pki.caFile })).status).toBe(200);
    expect(
      (await fetchListener('https', { ca: pki.caFile, cert: pki.clientCert, key: pki.clientKey }))
        .status,
    ).toBe(200);
    await expect(
      fetchListener('https', { ca: pki.caFile, cert: foreign.clientCert, key: foreign.clientKey }),
    ).rejects.toThrow();
  }, 30_000);

  it('min_version TLS13 refuses a TLS 1.2 client', async () => {
    await startListener({
      prometheusWebConfig: writeConfig({
        tls_server_config: { cert_file: '{cert}', key_file: '{key}', min_version: 'TLS13' },
      }),
    });
    await expect(
      fetchListener('https', { ca: pki.caFile, maxVersion: 'TLSv1.2' }),
    ).rejects.toThrow();
    expect((await fetchListener('https', { ca: pki.caFile })).status).toBe(200);
  });

  it('TLS and auth together', async () => {
    await startListener({
      prometheusWebConfig: writeConfig({
        tls_server_config: { cert_file: '{cert}', key_file: '{key}' },
        basic_auth_users: { e2e: '{hash}' },
      }),
    });
    expect((await fetchListener('https', { ca: pki.caFile })).status).toBe(401);
    expect(
      (
        await fetchListener('https', {
          ca: pki.caFile,
          headers: { authorization: basic('e2e', PASSWORD) },
        })
      ).status,
    ).toBe(200);
    expect(console.warn).not.toHaveBeenCalled();
  });
});

function bumpMtime(path: string, seconds: number): void {
  const later = statSync(path).mtimeMs / 1000 + seconds;
  utimesSync(path, later, later);
}

async function servedSerial(): Promise<string> {
  const { request } = await import('node:https');
  const { listenerAddress } = await import('../src/prom-listener.js');
  return new Promise((done, fail) => {
    const req = request(
      {
        host: '127.0.0.1',
        port: must(listenerAddress()).port,
        path: '/metrics',
        ca: readFileSync(pki.caFile),
        servername: 'localhost',
        agent: false,
      },
      (res) => {
        const socket = res.socket as import('node:tls').TLSSocket;
        done(socket.getPeerCertificate().serialNumber);
        res.resume();
      },
    );
    req.on('error', fail);
    req.end();
  });
}

describe('certificate rotation', () => {
  it('the reloader rebuilds only when the cert or key changes, and a broken one throws', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'rot-'));
    const cert = join(dir, 's.crt');
    const key = join(dir, 's.key');
    writeFileSync(cert, readFileSync(pki.certFile));
    writeFileSync(key, readFileSync(pki.keyFile));
    const reloader = new TlsReloader(cert, key, undefined, 'NoClientCert', 'TLSv1.2');
    const first = reloader.options;
    expect(reloader.refresh()).toBeUndefined();
    expect(reloader.options).toBe(first);
    const [newCert, newKey] = await pki.issue('rotated', SERVER_AUTH);
    writeFileSync(cert, readFileSync(newCert));
    writeFileSync(key, readFileSync(newKey));
    bumpMtime(cert, 10);
    const second = reloader.refresh();
    expect(second).toBeDefined();
    expect(reloader.options).toBe(second);
    expect(must(second).cert).toEqual(readFileSync(newCert));
    expect(reloader.refresh()).toBeUndefined();
    writeFileSync(key, 'garbage');
    bumpMtime(key, 20);
    expect(() => reloader.refresh()).toThrow();
    expect(reloader.options).toBe(second);
    // Still broken, still refused: the failed stamp is not remembered.
    expect(() => reloader.refresh()).toThrow();
  });

  it('a listener serves the rotated certificate without a restart, and refuses a broken one', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'rot-'));
    const cert = join(dir, 's.crt');
    const key = join(dir, 's.key');
    writeFileSync(cert, readFileSync(pki.certFile));
    writeFileSync(key, readFileSync(pki.keyFile));
    await startListener({
      prometheusWebConfig: writeConfig(
        { tls_server_config: { cert_file: 's.crt', key_file: 's.key' } },
        dir,
      ),
    });
    const before = await servedSerial();
    const [newCert, newKey] = await pki.issue('rotated', SERVER_AUTH);
    writeFileSync(cert, readFileSync(newCert));
    writeFileSync(key, readFileSync(newKey));
    bumpMtime(cert, 10);
    const after = await servedSerial();
    expect(after).not.toBe(before);
    writeFileSync(key, 'garbage');
    bumpMtime(key, 20);
    await expect(fetchListener('https', { ca: pki.caFile })).rejects.toThrow();
    writeFileSync(key, readFileSync(newKey));
    bumpMtime(key, 30);
    expect((await fetchListener('https', { ca: pki.caFile })).status).toBe(200);
  }, 30_000);
});
