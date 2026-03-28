// SPDX-FileCopyrightText: Copyright (c) 2025-2026 MindTenet LLC. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Re-exports sanitize() and DEFAULT_SANITIZE_FIELDS from pii.ts for backwards compatibility.
 * New code should import from './pii' directly.
 */
export { sanitize, DEFAULT_SANITIZE_FIELDS } from './pii';
