# Branch Protection Configuration

Apply these settings in GitHub → Settings → Branches → Branch protection rules → `main`:

## Required Settings

- **Require a pull request before merging**
  - Required approving reviews: 1
  - Dismiss stale pull request approvals when new commits are pushed: yes
- **Require status checks to pass before merging**
  - Require branches to be up to date before merging: yes
  - Required checks:
    - `quality (3.11)` (1. 🐍 CI — Python)
    - `typescript-quality` (2. 🟦 CI — TypeScript)
    - `docs-quality` (3. 📋 CI — Shared)
    - `conformance` (4. 📐 Spec Conformance)
    - `version-sync` (4. 📐 Spec Conformance)
    - `mutation-pr` (1. 🐍 CI — Python, PR only)
    - `typescript-mutation-pr` (2. 🟦 CI — TypeScript, PR only)
- **Do not allow bypassing the above settings**

## Apply via CLI

```bash
gh api repos/undef-games/undef-telemetry/branches/main/protection \
  --method PUT \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "quality (3.11)",
      "typescript-quality",
      "docs-quality",
      "conformance",
      "version-sync",
      "mutation-pr",
      "typescript-mutation-pr"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null
}
EOF
```
