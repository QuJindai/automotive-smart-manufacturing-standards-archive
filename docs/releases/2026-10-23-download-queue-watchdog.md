# Download queue watchdog repair

Status: implementation and acceptance in progress; not yet a release claim.

## Evidence and scope

At baseline `a98440fd`, production MCP and Drive services were reachable and the
latest real downloads on 2026-10-14 had independent Drive SHA-256 receipts. The
GitHub scheduler was active, but 49 schedule runs from October 15 to October 22
had intervals of 110.55–406.5 minutes. They started immediately once created and
completed within 16 seconds. The delay is before workflow-run creation, not in
the downloader. GitHub's internal reason is unknown.

The original immediate GitHub App dispatch remains. Its only independent
recovery was GitHub's best-effort cron. This repair adds a Supabase-controlled
recovery clock without changing source routing, provider support, artifact
integrity checks, Drive destinations, or existing download records.

## Repair contract

- Supabase Cron checks every five minutes; an empty queue creates no HTTP request
  and starts no GitHub runner. The existing GitHub cron remains as another fallback.
- `POST /internal/wake` is production-only and authenticated with a dedicated
  high-entropy Vault token. Only its SHA-256 is stored in the private state row.
  No PAT, model call, or GitHub private key is added to cron SQL.
- Only `QUEUED` jobs at least 60 seconds old or expired `CLAIMED` leases qualify.
  Live claims suppress additional wakes. Terminal, unresolved, authorization-
  required, and legacy descriptor jobs are not retried or rewritten.
- A revision compare-and-swap reserves a five-minute cooldown before dispatch;
  concurrent calls do not create duplicate dispatches. Sanitized outcomes are
  persisted independently from download jobs.
- Queue scans must reach newer jobs behind more than 20 ineligible old records.
- The database schedule starts disabled until the authenticated Edge route is
  deployed and its deny/empty behavior is checked.

## Verification gates

- [ ] New scheduler behavioral tests observed failing, then passing.
- [ ] Database predicate/privilege tests observed failing, then passing.
- [ ] Existing Node, Python, and browser CI regression gates pass.
- [ ] Missing/wrong authorization and staging wake attempts cannot dispatch.
- [ ] Empty cron tick records a heartbeat without invoking GitHub.
- [ ] Real isolated lost-dispatch job is recovered by the new clock and ends
  with independent Google Drive checksum verification.
- [ ] Normal plugin immediate dispatch still completes a small public file.
- [ ] Source, deployment, Git revision and rollback instructions reconciled.

## Operational and rollback boundaries

The `net` schema is not in this project's exposed PostgREST schemas. This is a
security dependency because `pg_net` temporarily holds request headers. Its
existing shared SQL grants were not broadened or revoked. The state table and
Vault deny reads to `anon` and `authenticated`; service-role credentials remain
server-only. Never expose `net` through the Data API or generic client SQL RPCs.

To stop only this new recovery clock (without touching download jobs or the
existing App dispatch), run as the database owner:

```sql
begin;
select cron.alter_job(jobid, active:=false)
from cron.job where jobname='download-queue-watchdog-v1';
update public.iaos_mcp_state
set payload=payload || '{"enabled":false}'::jsonb,
    revision=revision+1, updated_at=now()
where owner_id='00000000-0000-4000-8000-000000000091'
  and kind='download_executor_scheduler' and record_id='config';
commit;
```

If a complete Edge rollback is needed, redeploy the five `download-mcp` source
files from baseline `a98440fd` with their original relative names and existing
`verify_jwt=false` custom authentication. Preserve the private MCP path and App
configuration. Do not drop the shared state table, delete Vault entries, reset
jobs, or disable any other cron job. Retaining the dormant scheduler records is
safe and preserves evidence.

## References

- [GitHub schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [Supabase scheduled Edge Functions](https://supabase.com/docs/guides/functions/schedule-functions)
