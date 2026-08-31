# Download Plugin GitHub App Dispatch Design

## Status

Approved by the user on 2026-08-31. This design amends the five-minute polling decision in `2026-08-30-download-plugin-autonomous-closure-design.md`; every other control-plane, Drive, policy and executor boundary remains unchanged.

## Objective

Dispatch `download-executor.yml` immediately after a durable download job first enters `QUEUED`, while retaining the scheduled OIDC queue poll as a recovery path. The dispatch mechanism must not use a personal access token and must not make durable queue creation depend on GitHub availability.

## Selected approach

Register one private GitHub App owned by `QuJindai`, install it only on `QuJindai/automotive-smart-manufacturing-standards-archive`, and grant only:

- repository `Actions: write`; and
- repository `Metadata: read`.

No webhook is required. The App is private because it is an internal scheduler, not because the repository or ChatGPT plugin is private.

Supabase stores three deployment secrets:

- `DOWNLOAD_GITHUB_APP_ID`;
- `DOWNLOAD_GITHUB_APP_INSTALLATION_ID`; and
- `DOWNLOAD_GITHUB_APP_PRIVATE_KEY`.

The private key is the long-lived installation credential. `download-mcp` signs a GitHub App JWT with a lifetime below ten minutes, exchanges it for a repository-scoped installation token that expires after about one hour, and uses that token to call the workflow-dispatch REST endpoint. No installation token is persisted.

## Dispatch contract

The control plane dispatches only on a state transition into `QUEUED`:

- direct HTTPS `start_download`: new job is persisted, then dispatched;
- successful `resolve_download_sources`: the updated job is persisted, then dispatched;
- `retry_download`: the retry state is persisted, then dispatched; and
- an idempotent re-submission of an already queued resolution does not dispatch again.

The request is:

```text
POST /repos/QuJindai/automotive-smart-manufacturing-standards-archive/actions/workflows/download-executor.yml/dispatches
ref=main
```

GitHub API calls use `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2026-03-10`, bounded timeouts, and `Authorization: Bearer ...`. The private key, App JWT and installation token must never be returned, logged or persisted in job payloads.

## Failure semantics

Durability precedes dispatch. If configuration is missing, signing fails, GitHub is unavailable, or dispatch is rejected:

- the MCP tool still returns the already persisted `QUEUED` job;
- a sanitized `executor_dispatch` result reports `FALLBACK_POLLING` without secrets or response bodies;
- the existing five-minute scheduled workflow remains responsible for recovery; and
- the user is never told to create a descriptor commit.

A successful call reports `executor_dispatch.status=DISPATCHED`, the safe HTTP status, and workflow-run metadata only when GitHub returns it. This evidence is response metadata; executor claim/result state remains the durable proof of execution.

## App-token cache

One warm Edge Function isolate may reuse an installation token until sixty seconds before its expiry. Cache identity includes App ID and installation ID. A new isolate or an expired cache obtains a new installation token. A failed dispatch invalidates the cached token once and retries with one freshly exchanged token only when GitHub returns `401` or `403`.

## Security boundaries

- The GitHub App is installed on one selected repository, never all repositories.
- The App cannot read or write repository contents.
- Supabase secrets are configured through the hosted secret manager and never committed to Git or written to a temporary project file.
- The public MCP surface does not expose App configuration or token material.
- Scheduled GitHub OIDC claims remain repository/ref/workflow-bound exactly as before.
- Dispatch is best-effort orchestration; only OIDC-authenticated executor endpoints may claim or mutate executor state.

## Test strategy

Unit tests use a generated RSA key and injected HTTP transport to verify:

- App JWT `alg`, `iss`, `iat` and `exp` claims and a valid RSA signature;
- PKCS#8 and GitHub-style PKCS#1 PEM handling;
- installation-token exchange request path and headers;
- workflow-dispatch request path, headers and `ref=main` body;
- installation-token reuse and expiry refresh;
- one retry after cached-token `401`/`403`;
- secret-free failure evidence; and
- durable persistence occurring before dispatch, with dispatch failure leaving the job queued.

Production acceptance requires a fresh direct public PDF job to return `DISPATCHED`, obtain a non-null executor without waiting for the scheduled poll, and complete with PDF magic, exact bytes, SHA-256, `drive_verified=true`, Drive file ID and Drive metadata readback. The scheduled path is then retained and verified as a fallback rather than removed.

## Rollback

Redeploy the previous `download-mcp` version and remove the three Supabase App secrets. The scheduled OIDC workflow continues to drain the durable queue. Revoke the GitHub App private key or uninstall the App if credential compromise is suspected; queued jobs and Drive files are preserved.
