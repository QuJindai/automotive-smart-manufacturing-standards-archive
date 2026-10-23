# Download queue watchdog repair

Status: deployed and live acceptance passed on 2026-10-23 (Asia/Shanghai).

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

- [x] New scheduler behavioral tests observed failing, then passing.
- [x] Database predicate/privilege tests observed failing, then passing.
- [x] Existing Node, Python, and browser CI regression gates pass.
- [x] Missing/wrong authorization and staging wake attempts cannot dispatch.
- [x] Empty cron tick records a heartbeat without invoking GitHub.
- [x] Real isolated lost-dispatch job is recovered by the new clock and ends
  with independent Google Drive checksum verification.
- [x] Normal plugin immediate dispatch still completes a small public file.
- [x] Source, deployment, Git revision and rollback instructions reconciled.

## Deployment and live evidence

Implementation commit: `abb09c56a3ffc53cad53932d62d6bb293f28572c` on `main`.
Production `download-mcp` revision 27 and staging revision 30 serve
`0.5.1-queue-watchdog`. All six deployed production files matched the committed
source after line-ending normalization. Bundle SHA-256:
`15a8a2c7a6518786e5b21a67707fe766ff1225c5d6c9f2ee7f36750f2ad9317c`.

- [CI run 39833500356](https://github.com/QuJindai/automotive-smart-manufacturing-standards-archive/actions/runs/39833500356)
  passed, including real Chromium fallback for known- and unknown-length HTTPS
  sources. Local rerun: 70/70 Node tests; 48 executor Python tests passed, two
  browser tests skipped locally and covered by CI; 13 matrix/fetch tests passed.
- Missing and wrong bearer credentials returned HTTP 401. Staging wake returned
  HTTP 404. Both health endpoints returned HTTP 200 with the release version.
- Real PostgREST pagination: 21 temporary ineligible rows plus two existing
  legacy rows forced a second page. Authenticated request `77135` returned
  HTTP 200, `status=empty`, without dispatch. Exactly 21 tagged fixture rows were
  removed; zero remain. No historical download record was removed.
- Cron `download-queue-watchdog-v1` (job 16) was enabled. The initial empty tick at
  `2026-10-23T03:12:38Z` returned `IDLE`, without an HTTP request or GitHub wake.
- Lost-dispatch fault injection used the normal `buildInitialJob` constructor,
  then inserted one isolated QUEUED record without calling the immediate
  dispatcher. This is a persistence-to-dispatch fault test, not an API creation
  test. No timestamps were backdated and no manual wake was sent for this job.
  Job: `download-fbd6842047ad4e63a35306a75fd30770`.
- Natural cron run `176901` at `2026-10-23T03:15:00Z` succeeded. Its HTTP request
  `77142` returned HTTP 200, `dispatched`, with GitHub App run
  [39894005427](https://github.com/QuJindai/automotive-smart-manufacturing-standards-archive/actions/runs/39894005427).
  The workflow event was `workflow_dispatch`, created at `03:15:09Z`; the job
  was claimed at `03:15:18Z`.

The recovered NIST job completed at `2026-10-23T03:16:13.882Z`. Its 1,946,127-byte
PDF has SHA-256
`7576edb531d9848825814ee88e28b1795d3a84b435b4b797d3670eafdc4a89f1`.
Google Drive independently returned the same checksum, with
`checksum_method=google_drive_sha256`, `checksum_verified=true` and
`drive_verified=true`. File ID: `1oYlAMzX1EYoIt3aot9SlzqOWnrSRdU9W`.
The executor's normal continuation run `39894107955` then saw an empty queue.

After that continuation finished, a normal plugin `start_download` call created
`download-e0043062b9f84822bfd964c43dd48ccd` at `03:17:24.919Z`. Its response
reported immediate GitHub App dispatch to
[39894210382](https://github.com/QuJindai/automotive-smart-manufacturing-standards-archive/actions/runs/39894210382),
which claimed the job at `03:17:33.106Z` and completed at `03:18:19.491Z`.
`rfc3986.txt` is 141,811 bytes, with SHA-256
`3102dae4b68cebe40337730312fcb612297b8928547267e8b3d1ee6002b2d683`.
Its independent Drive receipt also matched; file ID:
`1ZsKld85vx7HfxZcW-vqrdcBy8OALOawl`. Both real workflows concluded `success`.

Times above are UTC; add eight hours for Asia/Shanghai. Both test files are
retained under `Google Drive/下载/插件验收/20261023-watchdog/` as evidence.

The second natural cron run, `176937`, succeeded at `03:20:00Z`, exactly five
minutes after the first. It recorded `IDLE`; `last_request_id` remained `77142`
and no new GitHub run was created by the watchdog. The normal executor retains
its existing one-run continuation after a completed job; that is separate from
the new empty-queue clock behavior.

Final database reconciliation at `03:20:35Z`: 83 COMPLETED (81 historical plus
the two acceptance jobs), 33 FAILED, four PARTIAL, two BLOCKED, three RESOLVING,
two legacy FETCHING, one AUTH_REQUIRED and zero QUEUED. All six historical
nonterminal records retained their original status and modification time.
Cron is active, config is enabled, and the temporary pagination fixture count
is zero. Detailed local machine-readable evidence is in the task output file
`download-watchdog-acceptance-20261023.json`.

## Acceptance limits

This closes the independent queue-recovery repair and regression gates, not a
new all-provider, bulk-volume or web Chat UI certification. The current plugin
connector was exercised end to end; no fresh browser conversation was sent in
this acceptance. No provider-specific branch was added. Existing download,
browser fallback and checksum behavior remained unchanged and passed the
regression suite. The five-minute interval is a queue-check cadence, not a hard
completion SLA; GitHub, Supabase and source/Drive availability still matter.

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
