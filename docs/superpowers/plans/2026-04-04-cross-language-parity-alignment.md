# Cross-Language Parity Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align observable behavior across Go, TypeScript, and Python so the same input produces the same output regardless of language.

**Architecture:** Six independent feature areas (PII keys, secret detection, backpressure defaults, error fingerprinting, required-keys validation, runtime reconfigure) each implemented via TDD, followed by cross-language parity test expansion. Changes are additive — no existing public APIs change shape.

**Tech Stack:** Go 1.25 (slog, crypto/sha256, regexp), TypeScript (Vitest), Python (pytest, structlog), YAML behavioral fixtures.

**Spec:** `docs/superpowers/specs/2026-04-04-cross-language-parity-alignment-design.md`

---

## Task 1: Extend behavioral fixtures with new test vectors

**Files:**
- Modify: `spec/behavioral_fixtures.yaml`

- [ ] **Step 1: Add secret detection fixtures**

Append to `spec/behavioral_fixtures.yaml`:

```yaml
  secret_detection:
    description: >
      String values matching known secret patterns are redacted regardless of key name.
      Minimum string length 20 before pattern matching.
    cases:
      - input: "AKIAIOSFODNN7EXAMPLE" # pragma: allowlist secret
        detected: true
        note: "AWS access key (20 chars)"
      - input: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0" # pragma: allowlist secret
        detected: true
        note: "JWT token"
      - input: "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklm" # pragma: allowlist secret
        detected: true
        note: "GitHub personal access token"
      - input: "not-a-secret"
        detected: false
        note: "Short string, no pattern match"
      - input: "hello world this is normal text"
        detected: false
        note: "Long string but no pattern match"

  default_sensitive_keys:
    description: >
      Canonical set of 17 default sensitive key names. Case-insensitive substring match.
    keys:
      - password
      - passwd
      - secret
      - token
      - api_key
      - apikey
      - auth
      - authorization
      - credential
      - private_key
      - ssn
      - credit_card
      - creditcard
      - cvv
      - pin
      - account_number
      - cookie

  error_fingerprint:
    description: >
      SHA-256 of colon-joined lowercase parts, first 12 hex chars.
      Parts: [exc_type_lower, basename1:func1, basename2:func2, basename3:func3]
      When no stack frames available, just the exc type.
    cases:
      - input: "valueerror"
        frames: []
        expected: "07be54796690"
        note: "No frames — hash of just 'valueerror'"
      - input: "typeerror"
        frames: ["module:main"]
        expected_length: 12
        note: "One frame — hash of 'typeerror:module:main'"
```

- [ ] **Step 2: Commit**

```bash
git add spec/behavioral_fixtures.yaml
git commit -m "spec: add secret detection, sensitive keys, and fingerprint fixtures"
```

---

## Task 2: Align Python default sensitive keys (5 → 17)

**Files:**
- Modify: `src/provide/telemetry/pii.py` (line 58)
- Test: `tests/parity/test_behavioral_fixtures.py`

- [ ] **Step 1: Write failing parity test**

Add to `tests/parity/test_behavioral_fixtures.py`:

```python
def test_parity_default_sensitive_keys_cookie():
    """cookie is in the canonical 17-key default sensitive list."""
    payload = {"cookie": "session=abc123"}
    result = sanitize_payload(payload, enabled=True)
    assert result["cookie"] == "***"


def test_parity_default_sensitive_keys_cvv():
    """cvv is in the canonical 17-key default sensitive list."""
    payload = {"cvv": "123"}
    result = sanitize_payload(payload, enabled=True)
    assert result["cvv"] == "***"


def test_parity_default_sensitive_keys_pin():
    """pin is in the canonical 17-key default sensitive list."""
    payload = {"pin": "9876"}
    result = sanitize_payload(payload, enabled=True)
    assert result["pin"] == "***"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python scripts/run_pytest_gate.py -k "test_parity_default_sensitive_keys" --no-cov -q`
Expected: FAIL — `cookie`, `cvv`, `pin` not in Python's current 5-key list

- [ ] **Step 3: Expand Python default sensitive keys**

In `src/provide/telemetry/pii.py`, replace line 58:

```python
_DEFAULT_SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "auth", "authorization", "credential", "private_key", "ssn",
    "credit_card", "creditcard", "cvv", "pin", "account_number", "cookie",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python scripts/run_pytest_gate.py -k "test_parity_default_sensitive_keys" --no-cov -q`
Expected: PASS

- [ ] **Step 5: Run full Python test suite**

Run: `uv run python scripts/run_pytest_gate.py`
Expected: All tests pass, 100% coverage

- [ ] **Step 6: Commit**

```bash
git add src/provide/telemetry/pii.py tests/parity/test_behavioral_fixtures.py
git commit -m "fix(python): expand default sensitive keys from 5 to 17 for cross-language parity"
```

---

## Task 3: Align TypeScript default sensitive keys (11 → 17)

**Files:**
- Modify: `typescript/src/pii.ts` (lines 19-31)
- Test: `typescript/tests/parity.test.ts`

- [ ] **Step 1: Write failing parity test**

Add to `typescript/tests/parity.test.ts` in the parity test section:

```typescript
describe('parity: default_sensitive_keys', () => {
  it('redacts credential key', () => {
    expect(sanitizePayload({ credential: 'abc' }, true)['credential']).toBe('***');
  });
  it('redacts cvv key', () => {
    expect(sanitizePayload({ cvv: '123' }, true)['cvv']).toBe('***');
  });
  it('redacts pin key', () => {
    expect(sanitizePayload({ pin: '9876' }, true)['pin']).toBe('***');
  });
  it('redacts account_number key', () => {
    expect(sanitizePayload({ account_number: '111' }, true)['account_number']).toBe('***');
  });
  it('redacts cookie key', () => {
    expect(sanitizePayload({ cookie: 'sess=x' }, true)['cookie']).toBe('***');
  });
  it('does NOT redact email key', () => {
    expect(sanitizePayload({ email: 'a@b.com' }, true)['email']).toBe('a@b.com');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd typescript && npx vitest run tests/parity.test.ts`
Expected: FAIL — `credential`, `cvv`, `pin`, `account_number` not in current TS list; `email` currently redacted but test expects it NOT to be

- [ ] **Step 3: Update TypeScript default sensitive keys**

In `typescript/src/pii.ts`, replace `DEFAULT_SANITIZE_FIELDS` (lines 19-31):

```typescript
export const DEFAULT_SANITIZE_FIELDS: readonly string[] = [
  'password',
  'passwd',
  'secret',
  'token',
  'api_key',
  'apikey',
  'auth',
  'authorization',
  'credential',
  'private_key',
  'ssn',
  'credit_card',
  'creditcard',
  'cvv',
  'pin',
  'account_number',
  'cookie',
];
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd typescript && npx vitest run tests/parity.test.ts`
Expected: PASS

- [ ] **Step 5: Run full TypeScript test suite**

Run: `cd typescript && npx vitest run`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add typescript/src/pii.ts typescript/tests/parity.test.ts
git commit -m "fix(typescript): align default sensitive keys to canonical 17-key list"
```

---

## Task 4: Add Go secret pattern detection

**Files:**
- Modify: `go/pii.go` (add regex patterns + detection function)
- Modify: `go/pii_test.go` (or create if absent)
- Modify: `go/parity_test.go`

- [ ] **Step 1: Write failing parity tests**

Add to `go/parity_test.go`:

```go
func TestParity_SecretDetection_AWSKey(t *testing.T) {
	payload := map[string]any{"data": "AKIAIOSFODNN7EXAMPLE"}
	result := SanitizePayload(payload, true, 0)
	if result["data"] != _piiRedacted {
		t.Errorf("expected AWS key redacted, got %v", result["data"])
	}
}

func TestParity_SecretDetection_JWT(t *testing.T) {
	payload := map[string]any{"data": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"}
	result := SanitizePayload(payload, true, 0)
	if result["data"] != _piiRedacted {
		t.Errorf("expected JWT redacted, got %v", result["data"])
	}
}

func TestParity_SecretDetection_GitHubToken(t *testing.T) {
	payload := map[string]any{"data": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklm"}
	result := SanitizePayload(payload, true, 0)
	if result["data"] != _piiRedacted {
		t.Errorf("expected GitHub token redacted, got %v", result["data"])
	}
}

func TestParity_SecretDetection_ShortString_NotRedacted(t *testing.T) {
	payload := map[string]any{"data": "not-a-secret"}
	result := SanitizePayload(payload, true, 0)
	if result["data"] != "not-a-secret" {
		t.Errorf("expected short string unchanged, got %v", result["data"])
	}
}

func TestParity_SecretDetection_LongNormalString_NotRedacted(t *testing.T) {
	payload := map[string]any{"data": "hello world this is normal text"}
	result := SanitizePayload(payload, true, 0)
	if result["data"] != "hello world this is normal text" {
		t.Errorf("expected normal string unchanged, got %v", result["data"])
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd go && go test -run TestParity_SecretDetection -v .`
Expected: FAIL — Go doesn't detect secrets in values

- [ ] **Step 3: Add secret detection to Go pii.go**

Add after `_isDefaultSensitiveKey` function (around line 194):

```go
import "regexp"  // add to imports

const _minSecretLength = 20

var _secretPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?:AKIA|ASIA)[A-Z0-9]{16}`),                // AWS access key
	regexp.MustCompile(`eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}`), // JWT
	regexp.MustCompile(`gh[pos]_[A-Za-z0-9_]{36,}`),                // GitHub token
	regexp.MustCompile(`[0-9a-fA-F]{40,}`),                         // Long hex
	regexp.MustCompile(`[A-Za-z0-9+/]{40,}={0,2}`),                 // Long base64
}

// _detectSecretInValue returns true if the string matches any known secret pattern.
func _detectSecretInValue(s string) bool {
	if len(s) < _minSecretLength {
		return false
	}
	for _, re := range _secretPatterns {
		if re.MatchString(s) {
			return true
		}
	}
	return false
}
```

Then modify `_sanitizeValue` — add secret detection after default key check (after line 135):

```go
	// Scan string values for known secret patterns.
	if str, ok := value.(string); ok && _detectSecretInValue(str) {
		return _piiRedacted, false
	}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd go && go test -run TestParity_SecretDetection -v .`
Expected: PASS

- [ ] **Step 5: Run full Go test suite + lint**

Run: `cd go && go test -race -coverprofile=coverage.out . && go tool cover -func=coverage.out | grep "^total" && golangci-lint run ./...`
Expected: 100% coverage, 0 lint issues

- [ ] **Step 6: Commit**

```bash
git add go/pii.go go/parity_test.go
git commit -m "feat(go): add secret pattern detection matching Python/TypeScript"
```

---

## Task 5: Align Go backpressure defaults to unlimited

**Files:**
- Modify: `go/backpressure.go` (lines 8, 30-35, 97-114)
- Modify: `go/backpressure_test.go`
- Modify: `go/parity_test.go`

- [ ] **Step 1: Write failing parity test**

Add to `go/parity_test.go`:

```go
func TestParity_Backpressure_DefaultUnlimited(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	policy := GetQueuePolicy()
	if policy.LogsMaxSize != 0 {
		t.Errorf("expected default LogsMaxSize=0 (unlimited), got %d", policy.LogsMaxSize)
	}
	if policy.TracesMaxSize != 0 {
		t.Errorf("expected default TracesMaxSize=0 (unlimited), got %d", policy.TracesMaxSize)
	}
	if policy.MetricsMaxSize != 0 {
		t.Errorf("expected default MetricsMaxSize=0 (unlimited), got %d", policy.MetricsMaxSize)
	}
}

func TestParity_Backpressure_UnlimitedAlwaysAcquires(t *testing.T) {
	_resetQueuePolicy()
	t.Cleanup(_resetQueuePolicy)

	// With unlimited (0), TryAcquire should always succeed
	for i := 0; i < 5000; i++ {
		if !TryAcquire(signalLogs) {
			t.Fatalf("TryAcquire failed at iteration %d with unlimited queue", i)
		}
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd go && go test -run TestParity_Backpressure -v .`
Expected: FAIL — default is 1000, not 0; TryAcquire fails after 1000

- [ ] **Step 3: Change default to 0 and handle unlimited in TryAcquire**

In `go/backpressure.go`:

Change `_defaultQueueSize` (line 8):
```go
const _defaultQueueSize = 0
```

Modify `TryAcquire` (lines 97-114) to skip channel when unlimited:
```go
func TryAcquire(signal string) bool {
	_queueMu.RLock()
	policy := _queuePolicy
	ch := _channelForSignal(signal)
	_queueMu.RUnlock()

	// Unlimited: maxSize <= 0 means no backpressure.
	maxSize := 0
	switch signal {
	case signalLogs:
		maxSize = policy.LogsMaxSize
	case signalTraces:
		maxSize = policy.TracesMaxSize
	case signalMetrics:
		maxSize = policy.MetricsMaxSize
	}
	if maxSize <= 0 {
		_incAcquired(signal)
		return true
	}

	if ch == nil {
		return false
	}

	select {
	case ch <- struct{}{}:
		_incAcquired(signal)
		return true
	default:
		_incDropped(signal)
		return false
	}
}
```

Also modify `Release` to skip when unlimited:
```go
func Release(signal string) {
	_queueMu.RLock()
	policy := _queuePolicy
	ch := _channelForSignal(signal)
	_queueMu.RUnlock()

	maxSize := 0
	switch signal {
	case signalLogs:
		maxSize = policy.LogsMaxSize
	case signalTraces:
		maxSize = policy.TracesMaxSize
	case signalMetrics:
		maxSize = policy.MetricsMaxSize
	}
	if maxSize <= 0 || ch == nil {
		return
	}

	select {
	case <-ch:
	default:
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd go && go test -run TestParity_Backpressure -v .`
Expected: PASS

- [ ] **Step 5: Update any tests that assert default=1000**

Search for tests asserting `_defaultQueueSize` or `1000` in backpressure tests and update them.

- [ ] **Step 6: Run full Go test suite + lint**

Run: `cd go && go test -race -coverprofile=coverage.out . && go tool cover -func=coverage.out | grep "^total" && golangci-lint run ./...`
Expected: 100% coverage, 0 lint issues

- [ ] **Step 7: Commit**

```bash
git add go/backpressure.go go/backpressure_test.go go/parity_test.go
git commit -m "fix(go): default backpressure to unlimited (0) matching TypeScript/Python"
```

---

## Task 6: Add Go error fingerprinting

**Files:**
- Create: `go/fingerprint.go`
- Modify: `go/logger.go` (Handle method, line 59)
- Test: `go/fingerprint_test.go`
- Modify: `go/parity_test.go`

- [ ] **Step 1: Write failing parity test**

Add to `go/parity_test.go`:

```go
func TestParity_ErrorFingerprint_NoFrames(t *testing.T) {
	// hash of just "valueerror" — must match Python/TypeScript
	fp := _computeErrorFingerprint("ValueError", nil)
	if len(fp) != 12 {
		t.Fatalf("expected 12-char fingerprint, got %d chars: %q", len(fp), fp)
	}
	// "valueerror" → SHA-256 → first 12 hex
	expected := "07be54796690"
	if fp != expected {
		t.Errorf("fingerprint mismatch: got %q, want %q", fp, expected)
	}
}

func TestParity_ErrorFingerprint_WithFrames(t *testing.T) {
	fp := _computeErrorFingerprintFromParts("TypeError", []string{"module:main", "handler:process"})
	if len(fp) != 12 {
		t.Fatalf("expected 12-char fingerprint, got %d chars: %q", len(fp), fp)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd go && go test -run TestParity_ErrorFingerprint -v .`
Expected: FAIL — function not defined

- [ ] **Step 3: Create go/fingerprint.go**

```go
// SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
// SPDX-License-Identifier: Apache-2.0

package telemetry

import (
	"crypto/sha256"
	"fmt"
	"runtime"
	"strings"
)

// _computeErrorFingerprint generates a stable 12-char hex fingerprint from
// exception type + top 3 stack frames from the given program counter.
// Matches the Python/TypeScript algorithm exactly.
func _computeErrorFingerprint(excType string, pcs []uintptr) string {
	parts := []string{strings.ToLower(excType)}
	if len(pcs) > 0 {
		frames := runtime.CallersFrames(pcs)
		count := 0
		for count < 3 {
			frame, more := frames.Next()
			if frame.Function == "" && !more {
				break
			}
			if frame.File != "" {
				base := _extractBasename(frame.File)
				fn := strings.ToLower(_extractFuncName(frame.Function))
				parts = append(parts, base+":"+fn)
				count++
			}
			if !more {
				break
			}
		}
	}
	return _shortHash12(strings.Join(parts, ":"))
}

// _computeErrorFingerprintFromParts generates a fingerprint from pre-extracted parts.
// Used for testing with known frame strings.
func _computeErrorFingerprintFromParts(excType string, frameParts []string) string {
	parts := []string{strings.ToLower(excType)}
	parts = append(parts, frameParts...)
	return _shortHash12(strings.Join(parts, ":"))
}

// _shortHash12 returns the first 12 hex characters of the SHA-256 hash.
func _shortHash12(input string) string {
	sum := sha256.Sum256([]byte(input))
	return fmt.Sprintf("%x", sum)[:12]
}

// _extractBasename extracts the filename without path or extension, lowercased.
func _extractBasename(file string) string {
	// Handle both / and \ separators
	file = strings.ReplaceAll(file, "\\", "/")
	if idx := strings.LastIndex(file, "/"); idx >= 0 {
		file = file[idx+1:]
	}
	// Remove extension
	if idx := strings.LastIndex(file, "."); idx >= 0 {
		file = file[:idx]
	}
	return strings.ToLower(file)
}

// _extractFuncName extracts just the function name from a fully qualified Go function path.
func _extractFuncName(fn string) string {
	// Go functions are like "github.com/pkg.Func" or "pkg.(*Type).Method"
	if idx := strings.LastIndex(fn, "."); idx >= 0 {
		return fn[idx+1:]
	}
	return fn
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd go && go test -run TestParity_ErrorFingerprint -v .`
Expected: PASS

- [ ] **Step 5: Wire into logger Handle method**

Add `applyErrorFingerprint` method to `go/logger.go` after `applyCallerFields`:

```go
// applyErrorFingerprint adds error_fingerprint when error attributes are present.
func (h *_telemetryHandler) applyErrorFingerprint(r slog.Record) slog.Record {
	var excName string
	r.Attrs(func(a slog.Attr) bool {
		switch a.Key {
		case "exc_info", "exc_name", "exception":
			excName = fmt.Sprint(a.Value.Any())
			return false
		}
		return true
	})
	if excName == "" {
		return r
	}
	fp := _computeErrorFingerprintFromParts(excName, nil)
	nr := slog.NewRecord(r.Time, r.Level, r.Message, r.PC)
	r.Attrs(func(a slog.Attr) bool {
		nr.AddAttrs(a)
		return true
	})
	nr.AddAttrs(slog.String("error_fingerprint", fp))
	return nr
}
```

Wire into `Handle` method — add after `applyCallerFields(r)`:

```go
r = h.applyErrorFingerprint(r)
```

Add `"fmt"` to logger.go imports if not already present.

- [ ] **Step 6: Write test for logger integration**

Add to `go/logger_test.go`:

```go
func TestHandler_ErrorFingerprint_Added(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("error occurred", slog.String("exc_name", "ValueError"))

	out := buf.String()
	if !strings.Contains(out, "error_fingerprint") {
		t.Errorf("expected error_fingerprint in output: %s", out)
	}
}

func TestHandler_ErrorFingerprint_NotAdded_WhenNoError(t *testing.T) {
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("normal message")

	if strings.Contains(buf.String(), "error_fingerprint") {
		t.Errorf("unexpected error_fingerprint in output: %s", buf.String())
	}
}
```

- [ ] **Step 7: Run full Go test suite + lint**

Run: `cd go && go test -race -coverprofile=coverage.out . && go tool cover -func=coverage.out | grep "^total" && golangci-lint run ./...`
Expected: 100% coverage, 0 lint issues

- [ ] **Step 8: Commit**

```bash
git add go/fingerprint.go go/fingerprint_test.go go/logger.go go/logger_test.go go/parity_test.go
git commit -m "feat(go): add error fingerprinting matching Python/TypeScript algorithm"
```

---

## Task 7: Add Go required-keys schema validation

**Files:**
- Modify: `go/schema.go`
- Modify: `go/logger.go` (applySchema method)
- Modify: `go/schema_test.go`
- Modify: `go/parity_test.go`

- [ ] **Step 1: Write failing test**

Add to `go/schema_test.go` (or `go/parity_test.go`):

```go
func TestValidateRequiredKeys_AllPresent(t *testing.T) {
	attrs := map[string]any{"domain": "user", "action": "login"}
	err := ValidateRequiredKeys(attrs, []string{"domain", "action"})
	if err != nil {
		t.Errorf("expected no error, got %v", err)
	}
}

func TestValidateRequiredKeys_MissingKey(t *testing.T) {
	attrs := map[string]any{"domain": "user"}
	err := ValidateRequiredKeys(attrs, []string{"domain", "action"})
	if err == nil {
		t.Error("expected error for missing required key 'action'")
	}
}

func TestValidateRequiredKeys_EmptyRequired(t *testing.T) {
	attrs := map[string]any{"domain": "user"}
	err := ValidateRequiredKeys(attrs, nil)
	if err != nil {
		t.Errorf("expected no error with nil required keys, got %v", err)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd go && go test -run TestValidateRequiredKeys -v .`
Expected: FAIL — function not defined

- [ ] **Step 3: Add ValidateRequiredKeys to schema.go**

Add to `go/schema.go` after `ValidateEventName`:

```go
// ValidateRequiredKeys returns an EventSchemaError if any required key is missing from attrs.
func ValidateRequiredKeys(attrs map[string]any, requiredKeys []string) error {
	for _, key := range requiredKeys {
		if _, ok := attrs[key]; !ok {
			return &EventSchemaError{Message: "missing required key: " + key}
		}
	}
	return nil
}
```

- [ ] **Step 4: Wire into applySchema in logger.go**

Modify `applySchema` in `go/logger.go`:

```go
func (h *_telemetryHandler) applySchema(r slog.Record) error {
	if !_strictSchema {
		return nil
	}
	if err := ValidateEventName(r.Message); err != nil {
		return err
	}
	if len(h.cfg.EventSchema.RequiredKeys) > 0 {
		attrs := _attrsToMap(r)
		return ValidateRequiredKeys(attrs, h.cfg.EventSchema.RequiredKeys)
	}
	return nil
}
```

- [ ] **Step 5: Write logger integration test**

Add to `go/logger_test.go`:

```go
func TestHandler_SchemaStrict_RequiredKeys_Drop(t *testing.T) {
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.EventSchema.RequiredKeys = []string{"domain"}
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	// Valid event name but missing "domain" attribute
	l.Info("user.auth.login")

	if buf.Len() != 0 {
		t.Errorf("expected record dropped for missing required key, got: %s", buf.String())
	}
}

func TestHandler_SchemaStrict_RequiredKeys_Pass(t *testing.T) {
	_strictSchema = true
	t.Cleanup(func() { _strictSchema = false })
	setupFullSampling(t)

	cfg := DefaultTelemetryConfig()
	cfg.EventSchema.RequiredKeys = []string{"domain"}
	cfg.Logging.Sanitize = false

	var buf bytes.Buffer
	l := newTestLogger(&buf, cfg, "")
	l.Info("user.auth.login", slog.String("domain", "user"))

	if buf.Len() == 0 {
		t.Error("expected record to pass when required key is present")
	}
}
```

- [ ] **Step 6: Run full Go test suite + lint**

Run: `cd go && go test -race -coverprofile=coverage.out . && go tool cover -func=coverage.out | grep "^total" && golangci-lint run ./...`
Expected: 100% coverage, 0 lint issues

- [ ] **Step 7: Commit**

```bash
git add go/schema.go go/schema_test.go go/logger.go go/logger_test.go
git commit -m "feat(go): add required-keys schema validation matching Python/TypeScript"
```

---

## Task 8: TypeScript reconfigureTelemetry — allow full restart

**Files:**
- Modify: `typescript/src/runtime.ts` (lines 73-90)
- Modify: `typescript/tests/runtime.test.ts`

- [ ] **Step 1: Update tests from "throws" to "succeeds"**

In `typescript/tests/runtime.test.ts`, update the three tests that assert `ConfigurationError`:

```typescript
  it('allows provider field changes by restarting when providers are registered', async () => {
    updateRuntimeConfig({ otelEnabled: false });
    _markProvidersRegistered();
    // Should NOT throw — should shutdown and reinit
    expect(() => reconfigureTelemetry({ otelEnabled: true })).not.toThrow();
  });

  it('allows otlpEndpoint change by restarting after registration', async () => {
    updateRuntimeConfig({ otlpEndpoint: 'http://old:4318' });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpEndpoint: 'http://new:4318' })).not.toThrow();
    expect(getRuntimeConfig().otlpEndpoint).toBe('http://new:4318');
  });

  it('allows otlpHeaders change by restarting after providers initialized', async () => {
    updateRuntimeConfig({ otlpHeaders: { 'x-api-key': 'old' } });
    _markProvidersRegistered();
    expect(() => reconfigureTelemetry({ otlpHeaders: { 'x-api-key': 'new' } })).not.toThrow();
  });
```

Also update the error message content test:

```typescript
  it('provider change triggers shutdown and reinit', () => {
    updateRuntimeConfig({ otlpEndpoint: 'http://old:4318' });
    _markProvidersRegistered();
    reconfigureTelemetry({ otlpEndpoint: 'http://new:4318' });
    // After reconfigure, providers should no longer be marked as registered
    // (they were shut down and the new setup hasn't registered them yet)
    expect(getRuntimeConfig().otlpEndpoint).toBe('http://new:4318');
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd typescript && npx vitest run tests/runtime.test.ts`
Expected: FAIL — `reconfigureTelemetry` still throws `ConfigurationError`

- [ ] **Step 3: Modify reconfigureTelemetry to allow restart**

In `typescript/src/runtime.ts`, replace the `reconfigureTelemetry` function (lines 73-90):

```typescript
export function reconfigureTelemetry(config: Partial<TelemetryConfig>): void {
  const current = getRuntimeConfig();
  const proposed: TelemetryConfig = { ...current, ...config };

  if (_providersRegistered) {
    const changed = PROVIDER_CHANGING_FIELDS.some(
      (k) => JSON.stringify(current[k]) !== JSON.stringify(proposed[k]),
    );
    if (changed) {
      // Shutdown existing providers, then reinit with new config.
      shutdownTelemetry();
      _providersRegistered = false;
    }
  }

  setupTelemetry(proposed);
  _activeConfig = proposed;
}
```

Ensure `shutdownTelemetry` is imported (check existing imports in the file).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd typescript && npx vitest run tests/runtime.test.ts`
Expected: PASS

- [ ] **Step 5: Run full TypeScript test suite**

Run: `cd typescript && npx vitest run`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add typescript/src/runtime.ts typescript/tests/runtime.test.ts
git commit -m "fix(typescript): allow reconfigureTelemetry to restart providers, matching Go/Python"
```

---

## Task 9: Add 15 missing Go parity test cases

**Files:**
- Modify: `go/parity_test.go`

- [ ] **Step 1: Add PII truncate parity tests (non-string conversion)**

Add to `go/parity_test.go`:

```go
func TestParity_PIITruncate_NonString(t *testing.T) {
	rules := []PIIRule{{Path: []string{"count"}, Mode: PIIModeTruncate, TruncateTo: 3}}
	SetPIIRules(rules)
	t.Cleanup(_resetPIIRules)

	payload := map[string]any{"count": 12345}
	result := SanitizePayload(payload, true, 0)
	// Non-string values are converted to string first, then truncated.
	if result["count"] != "123..." {
		t.Errorf("expected truncated non-string '123...', got %v", result["count"])
	}
}
```

- [ ] **Step 2: Add PII drop parity test**

```go
func TestParity_PIIDrop_RemovesKey(t *testing.T) {
	rules := []PIIRule{{Path: []string{"secret_data"}, Mode: PIIModeDrop}}
	SetPIIRules(rules)
	t.Cleanup(_resetPIIRules)

	payload := map[string]any{"secret_data": "top-secret", "keep": "visible"}
	result := SanitizePayload(payload, true, 0)
	if _, exists := result["secret_data"]; exists {
		t.Error("expected 'secret_data' to be dropped entirely")
	}
	if result["keep"] != "visible" {
		t.Errorf("expected 'keep' unchanged, got %v", result["keep"])
	}
}
```

- [ ] **Step 3: Add propagation guard parity tests**

```go
func TestParity_Propagation_BaggageAtLimit_Accepted(t *testing.T) {
	header := strings.Repeat("x", 8192)
	ctx := ExtractW3CContext(context.Background(), "", "", header)
	_, _, baggage := GetPropagationContext(ctx)
	if baggage != header {
		t.Error("expected baggage at limit (8192) to be accepted")
	}
}

func TestParity_Propagation_BaggageOverLimit_Discarded(t *testing.T) {
	header := strings.Repeat("x", 8193)
	ctx := ExtractW3CContext(context.Background(), "", "", header)
	_, _, baggage := GetPropagationContext(ctx)
	if baggage != "" {
		t.Error("expected baggage over limit (8193) to be discarded")
	}
}
```

- [ ] **Step 4: Add SLO classify parity tests**

```go
func TestParity_ClassifyError_200_Unknown(t *testing.T) {
	result := ClassifyError("", 200)
	if result["error.category"] != "unknown" {
		t.Errorf("expected unknown for 200, got %s", result["error.category"])
	}
}

func TestParity_ClassifyError_301_Unknown(t *testing.T) {
	result := ClassifyError("", 301)
	if result["error.category"] != "unknown" {
		t.Errorf("expected unknown for 301, got %s", result["error.category"])
	}
}

func TestParity_ClassifyError_TimeoutByExcName(t *testing.T) {
	result := ClassifyError("ConnectionTimeoutError", 503)
	if result["error.category"] != "timeout" {
		t.Errorf("expected timeout by exc name, got %s", result["error.category"])
	}
}

func TestParity_ClassifyError_599_ServerError(t *testing.T) {
	result := ClassifyError("ServerError", 599)
	if result["error.category"] != "server_error" {
		t.Errorf("expected server_error for 599, got %s", result["error.category"])
	}
}
```

- [ ] **Step 5: Run all parity tests**

Run: `cd go && go test -run TestParity -v .`
Expected: All PASS

- [ ] **Step 6: Run full Go test suite + lint**

Run: `cd go && go test -race -coverprofile=coverage.out . && go tool cover -func=coverage.out | grep "^total" && golangci-lint run ./...`
Expected: 100% coverage, 0 lint issues

- [ ] **Step 7: Commit**

```bash
git add go/parity_test.go
git commit -m "test(go): add 15 missing parity test cases for cross-language alignment"
```

---

## Task 10: Add new parity tests to TypeScript and Python

**Files:**
- Modify: `typescript/tests/parity.test.ts`
- Modify: `tests/parity/test_behavioral_fixtures.py`

- [ ] **Step 1: Add TypeScript parity tests for new behaviors**

Add to `typescript/tests/parity.test.ts`:

```typescript
describe('parity: secret_detection', () => {
  it('redacts AWS access key in value', () => {
    const result = sanitizePayload({ data: 'AKIAIOSFODNN7EXAMPLE' }, true);
    expect(result['data']).toBe('***');
  });
  it('redacts JWT in value', () => {
    const result = sanitizePayload(
      { data: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0' }, // pragma: allowlist secret
      true,
    );
    expect(result['data']).toBe('***');
  });
  it('does not redact short normal string', () => {
    const result = sanitizePayload({ data: 'not-a-secret' }, true);
    expect(result['data']).toBe('not-a-secret');
  });
});

describe('parity: backpressure_default', () => {
  it('default queue policy is unlimited (0)', () => {
    const policy = getQueuePolicy();
    expect(policy.maxLogs).toBe(0);
    expect(policy.maxTraces).toBe(0);
    expect(policy.maxMetrics).toBe(0);
  });
});

describe('parity: error_fingerprint', () => {
  it('produces 12-char hex for error name only', () => {
    const fp = computeErrorFingerprint('ValueError');
    expect(fp).toHaveLength(12);
    expect(fp).toBe('07be54796690');
  });
});

describe('parity: reconfigure_provider_change', () => {
  it('allows provider-changing reconfigure without error', () => {
    setupTelemetry({ otlpEndpoint: 'http://old:4318' });
    expect(() => reconfigureTelemetry({ otlpEndpoint: 'http://new:4318' })).not.toThrow();
  });
});
```

Ensure the needed imports are added at the top of the file (`sanitizePayload`, `getQueuePolicy`, `computeErrorFingerprint`, `reconfigureTelemetry`, `setupTelemetry`).

- [ ] **Step 2: Run TypeScript parity tests**

Run: `cd typescript && npx vitest run tests/parity.test.ts`
Expected: All PASS

- [ ] **Step 3: Add Python parity tests for new behaviors**

Add to `tests/parity/test_behavioral_fixtures.py`:

```python
def test_parity_secret_detection_aws_key():
    payload = {"data": "AKIAIOSFODNN7EXAMPLE"}  # pragma: allowlist secret
    result = sanitize_payload(payload, enabled=True)
    assert result["data"] == "***"


def test_parity_secret_detection_jwt():
    payload = {"data": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"}  # pragma: allowlist secret
    result = sanitize_payload(payload, enabled=True)
    assert result["data"] == "***"


def test_parity_secret_detection_normal_string_unchanged():
    payload = {"data": "not-a-secret"}
    result = sanitize_payload(payload, enabled=True)
    assert result["data"] == "not-a-secret"


def test_parity_error_fingerprint_no_frames():
    from provide.telemetry.logger.processors import _compute_error_fingerprint

    fp = _compute_error_fingerprint("ValueError", None)
    assert fp == "07be54796690"
    assert len(fp) == 12
```

- [ ] **Step 4: Run Python parity tests**

Run: `uv run python scripts/run_pytest_gate.py -k "test_parity" --no-cov -q`
Expected: All PASS

- [ ] **Step 5: Run full test suites**

Run TypeScript: `cd typescript && npx vitest run`
Run Python: `uv run python scripts/run_pytest_gate.py`
Expected: All tests pass in both

- [ ] **Step 6: Commit**

```bash
git add typescript/tests/parity.test.ts tests/parity/test_behavioral_fixtures.py
git commit -m "test: add cross-language parity tests for secret detection, fingerprint, reconfigure"
```

---

## Task 11: Final validation pass

- [ ] **Step 1: Run Go full gate**

```bash
cd go
go test -race -coverprofile=coverage.out .
go tool cover -func=coverage.out | grep "^total"
golangci-lint run ./...
```

Expected: 100% coverage, 0 lint issues

- [ ] **Step 2: Run Go mutation testing**

```bash
cd go && ~/go/bin/gremlins unleash .
```

Expected: 100% test efficacy (0 lived)

- [ ] **Step 3: Run TypeScript full gate**

```bash
cd typescript && npx vitest run
```

Expected: All tests pass

- [ ] **Step 4: Run Python full gate**

```bash
uv run python scripts/run_pytest_gate.py
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
```

Expected: All pass, 100% coverage

- [ ] **Step 5: Count Go parity tests**

```bash
cd go && go test -run TestParity -v . 2>&1 | grep -c "PASS:"
```

Expected: 39+ (up from 24)

- [ ] **Step 6: Final commit if any cleanup needed**

```bash
git add -A
git status
# Only commit if there are changes
```
