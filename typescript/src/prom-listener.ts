// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

/**
 * The Tier 3 standalone Prometheus listener. Node only.
 *
 * Serves responseFor() at PROVIDE_METRICS_PROMETHEUS_PATH on
 * OTEL_EXPORTER_PROMETHEUS_HOST:PORT, optionally secured by a Prometheus web
 * config (TLS, client certificates, bcrypt basic auth) restricted to the keys
 * prometheus_metrics.listener_security lists. It fails closed: any problem with
 * the web config keeps it from starting. Failures are logged and recorded as
 * the health snapshot's setupError; they never fail setup. Mirrors Python
 * provide.telemetry.metrics._prom_listener.
 *
 * Nothing in the browser build reaches this module: prom-setup.ts loads it
 * through a runtime-only import, and only under Node.
 */

import { createHash } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import {
  createServer as createHttpServer,
  type IncomingMessage,
  type Server as HttpServer,
  type ServerResponse,
} from 'node:http';
import { createServer as createHttpsServer, type Server as HttpsServer } from 'node:https';
import { isIP, type AddressInfo, type Socket } from 'node:net';
import { dirname, resolve } from 'node:path';
import { createSecureContext, type SecureContextOptions, type TLSSocket } from 'node:tls';
import { dynImportOtel } from './otel-dynimport.js';
import { PLAIN_TEXT, responseFor, type PrometheusResponse } from './prom-pull.js';
import { writeResponse } from './prometheus.js';

export const READ_TIMEOUT_MS = 10_000;
export const INSTALL_HINT =
  'install the optional peer dependencies yaml and bcryptjs (npm install yaml bcryptjs) to use PROVIDE_METRICS_PROMETHEUS_WEB_CONFIG';

const TOP_KEYS = ['basic_auth_users', 'tls_server_config'];
const TLS_KEYS = ['cert_file', 'client_auth_type', 'client_ca_file', 'key_file', 'min_version'];
const CLIENT_AUTH = ['NoClientCert', 'RequireAndVerifyClientCert', 'VerifyClientCertIfGiven'];
const MIN_VERSIONS: Readonly<Record<string, 'TLSv1.2' | 'TLSv1.3'>> = {
  TLS12: 'TLSv1.2',
  TLS13: 'TLSv1.3',
};
// Compared against when the user is unknown, so a wrong user name costs the
// same as a wrong password. Any well-formed cost-10 hash will do.
export const DUMMY_HASH = '$2a$10$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq';
const BCRYPT_HASH = /^\$2[aby]\$(0[4-9]|[12][0-9]|3[01])\$[./A-Za-z0-9]{53}$/;

const NOT_FOUND: PrometheusResponse = { status: 404, headers: [PLAIN_TEXT], body: 'not found\n' };
const UNAUTHORIZED: PrometheusResponse = {
  status: 401,
  headers: [['www-authenticate', 'Basic'], PLAIN_TEXT],
  body: 'unauthorized\n',
};

/** The web config cannot be used; the listener must not start. */
export class WebConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'WebConfigError';
  }
}

interface Bcrypt {
  compare(password: string, hash: string): Promise<boolean>;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
let importOptional: (pkg: string) => Promise<any> = dynImportOtel;

/** Swap the optional-dependency importer, to test the missing-dependency path. */
export function _setOptionalImporterForTests(importer?: (pkg: string) => Promise<any>): void {
  importOptional = importer ?? dynImportOtel;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

async function requireOptional<T>(pkg: string): Promise<T> {
  try {
    return (await importOptional(pkg)) as T;
  } catch {
    throw new WebConfigError(INSTALL_HINT);
  }
}

function isMapping(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Every failure caught here (fs, yaml, tls, net) is an Error. */
function errorText(err: unknown): string {
  return (err as Error).message;
}

/** Builds the TLS options, rebuilding them when the cert or key file changes. */
export class TlsReloader {
  readonly requestCert: boolean;
  readonly rejectUnauthorized: boolean;
  private _stamp: string;
  private _options: SecureContextOptions;

  constructor(
    private readonly cert: string,
    private readonly key: string,
    private readonly ca: string | undefined,
    clientAuth: string,
    private readonly minVersion: 'TLSv1.2' | 'TLSv1.3',
  ) {
    this.requestCert = clientAuth !== 'NoClientCert';
    this.rejectUnauthorized = clientAuth === 'RequireAndVerifyClientCert';
    this._stamp = this.stamp();
    this._options = this.build();
  }

  private stamp(): string {
    const mtime = (p: string): string => String(statSync(p, { bigint: true }).mtimeNs);
    return `${mtime(this.cert)}:${mtime(this.key)}`;
  }

  private build(): SecureContextOptions {
    const options: SecureContextOptions = {
      cert: readFileSync(this.cert),
      key: readFileSync(this.key),
      minVersion: this.minVersion,
    };
    if (this.ca !== undefined) options.ca = readFileSync(this.ca);
    createSecureContext(options); // throws on a bad PEM or a key that does not match
    return options;
  }

  /** The current options, or undefined when they have not changed since the last call. */
  refresh(): SecureContextOptions | undefined {
    const stamp = this.stamp();
    if (stamp === this._stamp) return undefined;
    const options = this.build();
    this._options = options;
    this._stamp = stamp;
    return options;
  }

  get options(): SecureContextOptions {
    return this._options;
  }
}

/** Basic auth users and TLS settings read from a web config. */
export class WebSecurity {
  private readonly verified = new Set<string>(); // sha256(user, password) of successful checks

  constructor(
    readonly users: ReadonlyMap<string, string> = new Map(),
    readonly tls: TlsReloader | undefined = undefined,
    private readonly bcrypt: Bcrypt | undefined = undefined,
  ) {}

  /** Whether an Authorization header satisfies basic auth (always, with no users). */
  async authorized(header: string | undefined): Promise<boolean> {
    if (this.users.size === 0) return true;
    const value = header ?? '';
    const space = value.indexOf(' ');
    const scheme = space < 0 ? value : value.slice(0, space);
    if (scheme.toLowerCase() !== 'basic') return false;
    const encoded = space < 0 ? '' : value.slice(space + 1);
    if (!/^[A-Za-z0-9+/]*={0,2}$/.test(encoded) || encoded.length % 4 !== 0) return false;
    const decoded = Buffer.from(encoded, 'base64');
    let text: string;
    try {
      text = new TextDecoder('utf-8', { fatal: true }).decode(decoded);
    } catch {
      return false;
    }
    const colon = text.indexOf(':');
    if (colon < 0) return false;
    return this.authenticate(text.slice(0, colon), text.slice(colon + 1));
  }

  async authenticate(user: string, password: string): Promise<boolean> {
    const bcrypt = this.bcrypt as Bcrypt;
    const digest = createHash('sha256').update(`${user}\0${password}`).digest('hex');
    if (this.verified.has(digest)) return true;
    const hashed = this.users.get(user);
    if (hashed === undefined) {
      await bcrypt.compare(password, DUMMY_HASH);
      return false;
    }
    if (!(await bcrypt.compare(password, hashed))) return false;
    this.verified.add(digest);
    return true;
  }
}

/** Read and validate a web config file; any problem throws WebConfigError. */
export async function loadWebConfig(path: string): Promise<WebSecurity> {
  const yaml = await requireOptional<{ parse(text: string): unknown }>('yaml');
  let data: unknown;
  try {
    data = yaml.parse(readFileSync(path, 'utf8'));
  } catch (err) {
    throw new WebConfigError(`web config ${path}: ${errorText(err)}`);
  }
  if (data === null || data === undefined) return new WebSecurity();
  if (!isMapping(data) || Object.keys(data).some((k) => !TOP_KEYS.includes(k))) {
    throw new WebConfigError(`web config ${path}: only ${TOP_KEYS.join(', ')} are supported`);
  }
  const users = usersFrom(data['basic_auth_users'] ?? {}, path);
  const bcrypt = users.size > 0 ? await requireOptional<Bcrypt>('bcryptjs') : undefined;
  const tls =
    'tls_server_config' in data ? tlsFrom(data['tls_server_config'], dirname(path)) : undefined;
  return new WebSecurity(users, tls, bcrypt);
}

function usersFrom(raw: unknown, path: string): Map<string, string> {
  if (!isMapping(raw)) {
    throw new WebConfigError(
      `web config ${path}: basic_auth_users must map user names to bcrypt hashes`,
    );
  }
  const users = new Map<string, string>();
  for (const [user, hashed] of Object.entries(raw)) {
    if (!BCRYPT_HASH.test(String(hashed))) {
      throw new WebConfigError(
        `web config ${path}: basic_auth_users[${user}] is not a bcrypt hash`,
      );
    }
    users.set(user, String(hashed));
  }
  return users;
}

function tlsFrom(raw: unknown, base: string): TlsReloader {
  if (!isMapping(raw) || Object.keys(raw).some((k) => !TLS_KEYS.includes(k))) {
    throw new WebConfigError(`tls_server_config: only ${TLS_KEYS.join(', ')} are supported`);
  }
  const cert = raw['cert_file'];
  const key = raw['key_file'];
  if (!cert || !key) throw new WebConfigError('tls_server_config needs cert_file and key_file');
  const minName = String(raw['min_version'] ?? 'TLS12');
  const minimum = Object.prototype.hasOwnProperty.call(MIN_VERSIONS, minName)
    ? MIN_VERSIONS[minName]
    : undefined;
  if (minimum === undefined) {
    throw new WebConfigError(
      `tls_server_config.min_version ${JSON.stringify(minName)}: want TLS12 or TLS13`,
    );
  }
  const caFile = raw['client_ca_file'] ? String(raw['client_ca_file']) : undefined;
  const clientAuth = String(
    raw['client_auth_type'] ?? (caFile ? 'RequireAndVerifyClientCert' : 'NoClientCert'),
  );
  if (!CLIENT_AUTH.includes(clientAuth)) {
    throw new WebConfigError(
      `tls_server_config.client_auth_type ${JSON.stringify(clientAuth)} is not supported`,
    );
  }
  if (clientAuth !== 'NoClientCert' && caFile === undefined) {
    throw new WebConfigError(
      `tls_server_config.client_auth_type ${clientAuth} needs client_ca_file`,
    );
  }
  try {
    return new TlsReloader(
      resolve(base, String(cert)),
      resolve(base, String(key)),
      caFile === undefined ? undefined : resolve(base, caFile),
      clientAuth,
      minimum,
    );
  } catch (err) {
    throw new WebConfigError(`tls_server_config: ${errorText(err)}`);
  }
}

/** The request target's path, without query or fragment. */
function pathOf(url: string): string {
  return url.split(/[?#]/, 1)[0] as string;
}

async function dispatch(
  req: IncomingMessage,
  path: string,
  security: WebSecurity,
): Promise<PrometheusResponse> {
  // A server request always carries its url and method.
  if (pathOf(req.url as string) !== path) return NOT_FOUND;
  if (!(await security.authorized(req.headers.authorization))) return UNAUTHORIZED;
  return responseFor(req.method as string, req.headers.accept);
}

type ListenerServer = HttpServer | HttpsServer;

function makeServer(path: string, security: WebSecurity): ListenerServer {
  const onRequest = (req: IncomingMessage, res: ServerResponse): void => {
    void dispatch(req, path, security).then((answer) => writeResponse(res, answer));
  };
  const tls = security.tls;
  const server: ListenerServer =
    tls === undefined
      ? createHttpServer(onRequest)
      : createHttpsServer(
          {
            ...tls.options,
            requestCert: tls.requestCert,
            rejectUnauthorized: tls.rejectUnauthorized,
            handshakeTimeout: READ_TIMEOUT_MS,
          },
          onRequest,
        );
  if (tls !== undefined) watchCertificates(server as HttpsServer, tls);
  server.headersTimeout = READ_TIMEOUT_MS;
  server.requestTimeout = READ_TIMEOUT_MS;
  server.setTimeout(READ_TIMEOUT_MS);
  return server;
}

/**
 * Re-read the certificate and key when they change, before each handshake.
 *
 * Prepended so it runs ahead of the TLS server's own connection listener,
 * which builds the handshake from the context current at that moment. A
 * rotation that cannot be loaded refuses the connection rather than serving
 * the old certificate past its replacement, and is retried on the next one.
 */
function watchCertificates(server: HttpsServer, tls: TlsReloader): void {
  server.prependListener('connection', (socket: Socket) => {
    try {
      const options = tls.refresh();
      if (options !== undefined) server.setSecureContext(options);
    } catch {
      socket.destroy();
    }
  });
  // VerifyClientCertIfGiven: a certificate that was offered must verify.
  server.on('secureConnection', (socket: TLSSocket) => {
    const offered = Object.keys(socket.getPeerCertificate()).length > 0;
    if (offered && !socket.authorized) socket.destroy();
  });
  server.on('tlsClientError', () => {
    // A failed handshake or a dropped client is not worth a stack trace.
  });
}

function listen(server: ListenerServer, host: string, port: number): Promise<void> {
  return new Promise((done, fail) => {
    server.once('error', fail);
    server.listen(port, host, () => {
      server.off('error', fail);
      done();
    });
  });
}

export function isLoopback(host: string): boolean {
  if (host === 'localhost') return true;
  const family = isIP(host);
  if (family === 4) return host.startsWith('127.');
  return family === 6 && new URL(`http://[${host}]`).hostname === '[::1]';
}

function warnExposure(host: string, security: WebSecurity): void {
  if (!isLoopback(host)) {
    console.warn(`[provide/telemetry] metrics.prometheus_listener.exposed: host=${host}`);
  }
  if (security.users.size > 0 && security.tls === undefined) {
    console.warn('[provide/telemetry] metrics.prometheus_listener.cleartext_auth');
  }
}

/** The listener settings; a change to any of them restarts it. */
export interface ListenerSettings {
  prometheusHost: string;
  prometheusPort: number;
  prometheusPath: string;
  prometheusWebConfig: string;
}

interface Running {
  key: string;
  server: ListenerServer;
}

let running: Running | undefined;
// Serializes sync and stop: each runs to completion before the next starts.
let queue: Promise<void> = Promise.resolve();

function keyOf(settings: ListenerSettings): string {
  return JSON.stringify([
    settings.prometheusHost,
    settings.prometheusPort,
    settings.prometheusPath,
    settings.prometheusWebConfig,
  ]);
}

async function start(settings: ListenerSettings): Promise<Running> {
  const security = settings.prometheusWebConfig
    ? await loadWebConfig(settings.prometheusWebConfig)
    : new WebSecurity();
  const server = makeServer(settings.prometheusPath, security);
  await listen(server, settings.prometheusHost, settings.prometheusPort);
  warnExposure(settings.prometheusHost, security);
  return { key: keyOf(settings), server };
}

async function stopRunning(): Promise<void> {
  const current = running;
  running = undefined;
  if (current === undefined) return;
  await new Promise<void>((done) => {
    current.server.close(() => done());
    current.server.closeAllConnections();
  });
}

function enqueue(step: () => Promise<void>): Promise<void> {
  queue = queue.then(step);
  return queue;
}

/**
 * Make the listener match settings: start, stop, restart on a changed key, or
 * leave it. enabled is whether the config asks for a listener at all.
 */
export function syncListener(
  settings: ListenerSettings,
  enabled: boolean,
  report: (error: string) => void,
): Promise<void> {
  return enqueue(async () => {
    if (!enabled) {
      await stopRunning();
      return;
    }
    if (running !== undefined && running.key === keyOf(settings)) return;
    await stopRunning();
    try {
      running = await start(settings);
    } catch (err) {
      const message = `prometheus listener: ${errorText(err)}`; // prom-setup's LISTENER_ERROR_PREFIX
      report(message);
      console.warn(`[provide/telemetry] metrics.prometheus_listener.failed: ${message}`);
    }
  });
}

/** Stop the listener if it runs. */
export function stopListener(): Promise<void> {
  return enqueue(stopRunning);
}

/** The bound host and port of the running listener, or undefined. */
export function listenerAddress(): { host: string; port: number } | undefined {
  if (running === undefined) return undefined;
  const bound = running.server.address() as AddressInfo;
  return { host: bound.address, port: bound.port };
}

/** The running server, for tests that inspect its settings. */
export function _listenerServerForTests(): ListenerServer | undefined {
  return running?.server;
}
