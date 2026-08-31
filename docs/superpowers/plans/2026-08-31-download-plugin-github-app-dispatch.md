# Download Plugin GitHub App Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trigger the existing GitHub download executor immediately when a durable job enters `QUEUED`, using a repository-scoped private GitHub App instead of a personal token.

**Architecture:** A focused WebCrypto module signs short-lived GitHub App JWTs, exchanges them for one-hour installation tokens, and calls the workflow-dispatch endpoint. The MCP persists the queue transition before calling the dispatcher, returns sanitized dispatch evidence, and retains scheduled OIDC polling as failure recovery.

**Tech Stack:** Supabase Edge Functions, TypeScript, WebCrypto RSA/RS256, GitHub REST API `2026-03-10`, Node test runner, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-31-download-plugin-github-app-dispatch-design.md`

## Global Constraints

- Never use or request a GitHub personal access token.
- Never commit or log the GitHub App private key, App JWT or installation token.
- Install the private GitHub App only on `QuJindai/automotive-smart-manufacturing-standards-archive` with repository `Actions: write` and `Metadata: read`; configure no webhook.
- Persist a job's transition to `QUEUED` before attempting dispatch.
- Dispatch failure must leave the job queued and fall back to the existing five-minute scheduled OIDC consumer.
- Do not weaken the existing repository/ref/workflow-bound OIDC checks.
- Preserve descriptor-push recovery, manual dispatch, queue-drain continuation and all download/Drive validation behavior.

---

### Task 1: Implement GitHub App authentication and workflow dispatch

**Files:**
- Create: `supabase/functions/download-mcp/github_app.ts`
- Create: `tests/download_mcp/github_app.test.mjs`

**Interfaces:**
- Consumes: `DOWNLOAD_GITHUB_APP_ID`, `DOWNLOAD_GITHUB_APP_INSTALLATION_ID`, `DOWNLOAD_GITHUB_APP_PRIVATE_KEY` plus fixed owner/repository/workflow/ref values supplied by the caller.
- Produces: `GitHubAppDispatcher.dispatch(): Promise<ExecutorDispatchEvidence>` and `dispatchAfterDurableQueue(job, persist, dispatcher): Promise<Record<string, unknown>>`.

- [ ] **Step 1: Write failing JWT tests**

Generate an RSA key pair inside `tests/download_mcp/github_app.test.mjs`, export both PKCS#8 and PKCS#1 PEM variants, call the intended JWT function and assert literal claims:

```js
assert.equal(header.alg, "RS256");
assert.equal(payload.iss, "12345");
assert.equal(payload.iat, 1_799_999_940);
assert.equal(payload.exp, 1_800_000_540);
assert.equal(await verifyJwtSignature(jwt, publicKey), true);
```

The production change that makes these tests pass is standards-compliant PKCS#8/PKCS#1 import and RSASSA-PKCS1-v1_5 signing.

- [ ] **Step 2: Run the JWT tests and observe the missing-module failure**

Run:

```powershell
node --test tests/download_mcp/github_app.test.mjs
```

Expected: FAIL because `github_app.ts` and its exported API do not exist.

- [ ] **Step 3: Implement minimal PEM and JWT helpers**

In `github_app.ts`, implement WebCrypto-only helpers that:

- parse `-----BEGIN PRIVATE KEY-----` as PKCS#8;
- wrap `-----BEGIN RSA PRIVATE KEY-----` PKCS#1 DER in a PKCS#8 `PrivateKeyInfo` envelope;
- import `RSASSA-PKCS1-v1_5` with SHA-256;
- build a base64url JWT header `{"alg":"RS256","typ":"JWT"}`; and
- use `iat=now-60`, `exp=now+540`, and string App ID as `iss`.

Do not add a runtime dependency for signing.

- [ ] **Step 4: Run the JWT tests until both PEM variants pass**

Run the Task 1 test file and require zero failures.

- [ ] **Step 5: Write failing HTTP-contract and cache tests**

Use an injected `fetch` implementation to assert, from literal fixtures:

1. token exchange calls `POST https://api.github.com/app/installations/67890/access_tokens` with an App JWT;
2. dispatch calls `POST https://api.github.com/repos/QuJindai/automotive-smart-manufacturing-standards-archive/actions/workflows/download-executor.yml/dispatches` with the installation token and `{"ref":"main"}`;
3. a token expiring more than sixty seconds in the future is reused;
4. an expired token is exchanged again;
5. cached-token `401` triggers exactly one fresh-token retry; and
6. errors contain only a safe code/status, never the private key, App JWT, installation token or response body.

- [ ] **Step 6: Verify the HTTP-contract tests fail for missing behavior**

Run the Task 1 test file and confirm the new tests fail for missing dispatch behavior, not fixture or syntax errors.

- [ ] **Step 7: Implement `GitHubAppDispatcher`**

Implement constructor-injected environment, clock, WebCrypto and fetch dependencies. Accept both `200` and `204` dispatch responses. Return one of:

```ts
type ExecutorDispatchEvidence =
  | { mechanism: "github_app"; status: "DISPATCHED"; http_status: number; workflow_run_id?: number; run_url?: string }
  | { mechanism: "github_app"; status: "FALLBACK_POLLING"; error_code: string; http_status?: number; retry_after_seconds: 300 };
```

Invalidate the installation-token cache and retry once only for `401` or `403` from workflow dispatch.

- [ ] **Step 8: Add and test durable-first orchestration**

`dispatchAfterDurableQueue` must call the injected persistence function first. It dispatches only when the persisted job status is `QUEUED`; it returns the queued job plus `executor_dispatch` evidence. A thrown or failed dispatch becomes `FALLBACK_POLLING` and does not reject the tool operation. Assert call order and durable queued state in the test.

- [ ] **Step 9: Run Task 1 and existing MCP tests**

```powershell
node --test tests/download_mcp/github_app.test.mjs tests/download_mcp/core.test.mjs
```

- [ ] **Step 10: Commit Task 1**

```powershell
git add supabase/functions/download-mcp/github_app.ts tests/download_mcp/github_app.test.mjs
git commit -m "feat: dispatch download executor with GitHub App"
```

---

### Task 2: Integrate durable dispatch into MCP queue transitions

**Files:**
- Modify: `supabase/functions/download-mcp/index.ts`
- Modify: `supabase/functions/download-mcp/core.ts`
- Modify: `tests/download_mcp/core.test.mjs`
- Modify: `docs/ARCHIVE_WORKFLOW.md`

**Interfaces:**
- Consumes: Task 1 `GitHubAppDispatcher` and `dispatchAfterDurableQueue`.
- Produces: `start_download`, `resolve_download_sources`, and `retry_download` responses with optional sanitized `executor_dispatch` evidence.

- [ ] **Step 1: Write failing state-transition tests**

Add assertions that direct creation, first successful resolution and retry are dispatch-eligible, while `RESOLVING`, `BLOCKED` and an idempotent already-queued resolution are not. Export a pure predicate if needed; the test must exercise observable transition behavior rather than source text.

- [ ] **Step 2: Run the MCP tests and confirm the transition assertions fail**

```powershell
node --test tests/download_mcp/core.test.mjs
```

- [ ] **Step 3: Integrate the dispatcher after durable writes**

Instantiate one dispatcher per warm isolate from Supabase secrets. For direct `start_download`, persist before dispatch. For resolution and retry, persist the new state before dispatch and pass the previous state so an idempotent already-queued resolution cannot create a duplicate run. Never dispatch `get_download`, `resume_download`, `finalize_download`, `RESOLVING` or `BLOCKED` results.

- [ ] **Step 4: Expose only sanitized dispatch evidence**

Add optional `executor_dispatch` to the MCP job output schema with the two literal status forms from Task 1. Bump `SERVER_VERSION` to `0.5.0-github-app-dispatch`. Do not expose configuration-presence booleans or credential identifiers.

- [ ] **Step 5: Run MCP tests and the full local regression suites**

```powershell
node --test tests/download_mcp/*.test.mjs tests/download_drive/*.test.mjs
python -m unittest discover -s tests/download_executor -v
```

- [ ] **Step 6: Document the operating model**

Update `docs/ARCHIVE_WORKFLOW.md` to state that a private repository-scoped GitHub App triggers immediate workflow dispatch; App failure leaves the job queued for five-minute OIDC polling; no PAT, descriptor commit or content permission exists.

- [ ] **Step 7: Commit Task 2**

```powershell
git add supabase/functions/download-mcp/index.ts supabase/functions/download-mcp/core.ts tests/download_mcp/core.test.mjs docs/ARCHIVE_WORKFLOW.md
git commit -m "feat: trigger queued downloads immediately"
```

---

### Task 3: Configure, deploy and prove the production path

**Files:**
- Production deploy: `supabase/functions/download-mcp/**`
- External configuration: private GitHub App and Supabase hosted secrets
- Evidence: GitHub App installation, Supabase function version/logs, download job, Actions run and Drive metadata

**Interfaces:**
- Consumes: reviewed Tasks 1-2, existing production `download-executor.yml`, existing `download-drive` and connected Google Drive.
- Produces: production `download-mcp` with immediate dispatch and a complete direct-PDF acceptance record.

- [ ] **Step 1: Register the private GitHub App**

In the authenticated GitHub account, create one private App named for the download executor, set webhook inactive, grant repository `Actions: write` and `Metadata: read`, generate one private key, and install the App only on `QuJindai/automotive-smart-manufacturing-standards-archive`. Record App ID and installation ID without displaying the private key.

- [ ] **Step 2: Store hosted secrets without a repository file**

Add `DOWNLOAD_GITHUB_APP_ID`, `DOWNLOAD_GITHUB_APP_INSTALLATION_ID` and `DOWNLOAD_GITHUB_APP_PRIVATE_KEY` to Supabase Edge Function secrets. Verify names are present; do not read their values back or create `.env` files.

- [ ] **Step 3: Publish source and require green CI**

Update the shared branch only by fast-forward or reviewed commit-tree update. Require all Node and Python download suites in `Download Executor CI` to pass before production deployment.

- [ ] **Step 4: Deploy `download-mcp` with rollback version recorded**

Deploy the complete source set with `verify_jwt=false` because the fixed private MCP capability and repository/ref/workflow-bound executor OIDC are enforced in the function body. Confirm the new version is active and `/health` reports `0.5.0-github-app-dispatch`; preserve the previous active version number for rollback.

- [ ] **Step 5: Run the direct public PDF gate**

Create one fresh small official public PDF job in a new acceptance folder. Require the initial response to contain:

```text
status=QUEUED
executor_dispatch.status=DISPATCHED
```

Then poll the durable job and require executor claim without waiting for the scheduled five-minute boundary, `%PDF-` validation, non-zero exact bytes, 64-character lowercase SHA-256, `status=COMPLETED`, `drive_verified=true`, a Drive file ID and the expected Drive leaf folder.

- [ ] **Step 6: Independently verify GitHub and Drive evidence**

Read the matching GitHub Actions run and Drive metadata. The run must use `workflow_dispatch`, complete successfully and name the same `download_id`; Drive must report the same filename, byte size and expected parent folder as the completed job.

- [ ] **Step 7: Verify fallback remains present**

Inspect the production workflow and require `schedule`, manual `workflow_dispatch`, OIDC claim and queue-continuation behavior to remain. Do not deliberately corrupt or revoke the production App credential for this check.

- [ ] **Step 8: Final verification and release decision**

Freshly run both local suites, inspect production function logs for the gate interval, query the final job, and verify no unexplained 5xx, secret-bearing log, hanging claim or unverified Drive reference. If immediate dispatch fails, leave the job queued, roll back only `download-mcp`, and keep bulk release blocked.
