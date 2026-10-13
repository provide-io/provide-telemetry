#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
#
# Generate a throwaway CA, a server certificate for localhost/127.0.0.1, and a
# Prometheus --web.config.file that requires TLS and basic auth, for the
# TLS + basic-auth run of e2e/test_prometheus_push_e2e.py.
#
# Usage: ci/prometheus-tls-setup.sh <output-dir>
#
# Writes ca.crt, server.crt, server.key, web-config.yml (TLS + basic auth) and
# auth-only.yml (basic auth over plain HTTP) into <output-dir>.
# Nothing here is a real secret: the keys are generated per run and the
# password is the fixed test value below, whose bcrypt hash is in the config.
set -euo pipefail

out="${1:?usage: $0 <output-dir>}"
mkdir -p "$out"
cd "$out"

# Python 3.13+ verifies with VERIFY_X509_STRICT, which rejects a CA without a
# keyUsage extension and a leaf without an authorityKeyIdentifier, so both are
# spelled out rather than left to openssl's defaults.
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=provide-telemetry e2e CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -addext "subjectKeyIdentifier=hash" \
  -keyout ca.key -out ca.crt 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=localhost" \
  -keyout server.key -out server.csr 2>/dev/null
cat > server.ext <<'EXT'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:localhost,IP:127.0.0.1
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid
EXT
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 2 \
  -extfile server.ext -out server.crt 2>/dev/null
rm -f server.csr server.ext ca.srl ca.key
# The Prometheus container runs as nobody; it must be able to read the key.
chmod 644 server.key

# User "e2e", password "e2e-test-only-password" (see PROMETHEUS_BASIC_AUTH_* in
# the prometheus-push job). Paths are relative to this file.
cat > web-config.yml <<'YAML'
tls_server_config:
  cert_file: server.crt
  key_file: server.key
basic_auth_users:
  e2e: $2a$10$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq
YAML
cat > auth-only.yml <<'YAML'
basic_auth_users:
  e2e: $2a$10$WuJ86tQzfCxkRPXM1G759Oi0am1AacPdbzSZS/UqQ3ePrV6MohbZq
YAML
echo "$out"
