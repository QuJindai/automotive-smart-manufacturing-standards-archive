-- Run with the database owner. No changes survive this test transaction.
begin;
do $test$
begin
  if to_regprocedure('public.download_scheduler_may_need_wake(jsonb)') is null then
    raise exception 'watchdog queue predicate is not installed';
  end if;
  if not public.download_scheduler_may_need_wake('{"status":"QUEUED"}') then
    raise exception 'queued work must be visible to the watchdog';
  end if;
  if not public.download_scheduler_may_need_wake('{"status":"FETCHING","executor":{"status":"CLAIMED"}}') then
    raise exception 'claimed work must reach the Edge lease check';
  end if;
  if public.download_scheduler_may_need_wake('{"status":"FETCHING","executor":null}')
    or public.download_scheduler_may_need_wake('{"status":"COMPLETED"}')
    or public.download_scheduler_may_need_wake('{"status":"FAILED"}')
    or public.download_scheduler_may_need_wake('{"status":"PARTIAL"}')
    or public.download_scheduler_may_need_wake('{"status":"RESOLVING"}')
    or public.download_scheduler_may_need_wake('{"status":"BLOCKED"}')
    or public.download_scheduler_may_need_wake('{"status":"AUTH_REQUIRED"}')
    or public.download_scheduler_may_need_wake('{}')
    or public.download_scheduler_may_need_wake('null') then
    raise exception 'legacy and terminal tasks must not wake the executor';
  end if;
  if has_function_privilege('anon','public.download_scheduler_tick()','execute')
    or has_function_privilege('authenticated','public.download_scheduler_tick()','execute')
    or has_function_privilege('service_role','public.download_scheduler_tick()','execute') then
    raise exception 'only the database owner may invoke the credential-bearing cron tick';
  end if;
  if (select prosecdef from pg_proc where oid='public.download_scheduler_tick()'::regprocedure) then
    raise exception 'cron tick must not elevate caller privileges';
  end if;
  if has_table_privilege('anon','public.iaos_mcp_state','SELECT')
    or has_table_privilege('authenticated','public.iaos_mcp_state','SELECT')
    or has_table_privilege('anon','vault.decrypted_secrets','SELECT')
    or has_table_privilege('authenticated','vault.decrypted_secrets','SELECT') then
    raise exception 'scheduler configuration and Vault must remain server-only';
  end if;
  if exists(select 1 from pg_db_role_setting s join pg_roles r on r.oid=s.setrole
    cross join lateral unnest(s.setconfig) cfg
    cross join lateral unnest(string_to_array(substring(cfg from 'pgrst.db_schemas=(.*)'),',')) schema_name
    where r.rolname='authenticator' and trim(schema_name)='net') then
    raise exception 'pg_net request headers must not be exposed through the Data API';
  end if;
end
$test$;
do $integration$
declare
  result jsonb;
  queued_request bigint;
begin
  -- Never interfere with a user's active queue. Test inserts are uncommitted;
  -- pg_net starts requests only after COMMIT, and this file always ROLLBACKs.
  if exists(select 1 from public.iaos_mcp_state
    where owner_id='00000000-0000-4000-8000-000000000091' and kind='download_job'
      and public.download_scheduler_may_need_wake(payload)) then
    raise exception 'run isolated database integration test only when the real queue is empty';
  end if;
  update public.iaos_mcp_state set payload=payload || '{"enabled":true}'::jsonb
    where owner_id='00000000-0000-4000-8000-000000000091'
      and kind='download_executor_scheduler' and record_id='config';
  result := public.download_scheduler_tick();
  if result->>'last_tick_status' <> 'IDLE' then
    raise exception 'empty queue must not enqueue an HTTP request';
  end if;
  insert into public.iaos_mcp_state(owner_id,kind,record_id,payload)
    values('00000000-0000-4000-8000-000000000091','download_job','watchdog-sql-rollback-fixture',
      '{"download_id":"watchdog-sql-rollback-fixture","status":"QUEUED"}');
  result := public.download_scheduler_tick();
  if result->>'last_tick_status' <> 'WAKE_REQUESTED' then
    raise exception 'queued work must enqueue the authenticated Edge wake';
  end if;
  queued_request := (result->>'last_request_id')::bigint;
  if not exists(select 1 from net.http_request_queue q
    join public.iaos_mcp_state c on c.owner_id='00000000-0000-4000-8000-000000000091'
      and c.kind='download_executor_scheduler' and c.record_id='config'
    where q.id=queued_request and q.method='POST'
      and q.url='https://ezvfqrhzucjvkwnnbjux.supabase.co/functions/v1/download-mcp/internal/wake'
      and encode(extensions.digest(substring(q.headers->>'Authorization' from 8),'sha256'),'hex')=c.payload->>'token_sha256'
      and q.timeout_milliseconds=60000) then
    raise exception 'wake must target the fixed production route with its dedicated Vault credential';
  end if;
  if exists(select 1 from public.iaos_mcp_state
    where owner_id='00000000-0000-4000-8000-000000000091' and kind='download_executor_scheduler'
      and record_id='clock' and (payload ? 'token' or payload ? 'authorization')) then
    raise exception 'clock audit must not retain credentials';
  end if;
end
$integration$;
rollback;
