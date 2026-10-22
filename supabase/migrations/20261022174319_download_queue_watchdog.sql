-- Recovery clock independent of GitHub's best-effort schedule.
-- Existing extensions: pg_cron, pg_net, pgcrypto and supabase_vault.
-- No plaintext credential is stored in migration history or cron.job.command.
do $setup$
declare
  scheduler_token text;
begin
  select decrypted_secret into scheduler_token from vault.decrypted_secrets
    where name = 'download_scheduler_token_v1';
  if scheduler_token is null then
    scheduler_token := encode(extensions.gen_random_bytes(32), 'hex');
    perform vault.create_secret(scheduler_token, 'download_scheduler_token_v1',
      'Download queue watchdog only; never a GitHub or Google credential');
  end if;
  insert into public.iaos_mcp_state(owner_id,kind,record_id,payload)
  values ('00000000-0000-4000-8000-000000000091','download_executor_scheduler','config',
    jsonb_build_object('token_sha256',encode(extensions.digest(scheduler_token,'sha256'),'hex'),
      'enabled',false))
  on conflict(owner_id,kind,record_id) do update
    set payload=iaos_mcp_state.payload || jsonb_build_object('token_sha256',excluded.payload->>'token_sha256'),
      revision=iaos_mcp_state.revision+1,updated_at=now();
  insert into public.iaos_mcp_state(owner_id,kind,record_id,payload)
  values ('00000000-0000-4000-8000-000000000091','download_executor_scheduler','dispatcher','{}')
  on conflict(owner_id,kind,record_id) do nothing;
end
$setup$;

-- Deliberately coarse: the Edge coordinator applies age, lease and cooldown
-- checks using the same eligibility predicate as the executor claim path.
create or replace function public.download_scheduler_may_need_wake(job jsonb)
returns boolean language sql immutable set search_path = '' as $function$
  select coalesce(job->>'status'='QUEUED' or
    (job->>'status'='FETCHING' and job->'executor'->>'status'='CLAIMED'),false);
$function$;
revoke all on function public.download_scheduler_may_need_wake(jsonb) from public,anon,authenticated,service_role;

create or replace function public.download_scheduler_tick()
returns jsonb language plpgsql security invoker set search_path = '' as $function$
declare
  scheduler_config jsonb;
  scheduler_token text;
  tick_result jsonb;
  request_id bigint;
  tick_at timestamptz := clock_timestamp();
begin
  if not pg_try_advisory_xact_lock(hashtextextended('download-queue-watchdog-v1',0)) then
    return jsonb_build_object('status','BUSY');
  end if;
  select payload into scheduler_config from public.iaos_mcp_state
    where owner_id='00000000-0000-4000-8000-000000000091'
      and kind='download_executor_scheduler' and record_id='config';
  if coalesce(scheduler_config->>'enabled','false') <> 'true' then
    tick_result := jsonb_build_object('last_tick_status','DISABLED');
  elsif not exists (
    select 1 from public.iaos_mcp_state
    where owner_id='00000000-0000-4000-8000-000000000091'
      and kind='download_job' and public.download_scheduler_may_need_wake(payload)
  ) then
    tick_result := jsonb_build_object('last_tick_status','IDLE');
  else
    select decrypted_secret into scheduler_token from vault.decrypted_secrets
      where name='download_scheduler_token_v1';
    if scheduler_token is null or
      encode(extensions.digest(scheduler_token,'sha256'),'hex') is distinct from scheduler_config->>'token_sha256' then
      tick_result := jsonb_build_object('last_tick_status','TOKEN_CONFIGURATION_INVALID');
    else
      select net.http_post(
        url:='https://ezvfqrhzucjvkwnnbjux.supabase.co/functions/v1/download-mcp/internal/wake',
        body:='{}'::jsonb,
        headers:=jsonb_build_object('Content-Type','application/json','Authorization','Bearer ' || scheduler_token),
        timeout_milliseconds:=60000
      ) into request_id;
      tick_result := jsonb_build_object('last_tick_status','WAKE_REQUESTED',
        'last_request_id',request_id,'last_request_at',tick_at);
    end if;
  end if;
  tick_result := tick_result || jsonb_build_object('last_tick_at',tick_at);
  insert into public.iaos_mcp_state(owner_id,kind,record_id,payload)
    values('00000000-0000-4000-8000-000000000091','download_executor_scheduler','clock',tick_result)
  on conflict(owner_id,kind,record_id) do update
    set payload=iaos_mcp_state.payload || excluded.payload,
      revision=iaos_mcp_state.revision+1,updated_at=now();
  return tick_result;
end
$function$;
-- Called by the existing database-owner cron connection only. Never expose a
-- credential-bearing SECURITY DEFINER RPC to API clients.
revoke all on function public.download_scheduler_tick() from public,anon,authenticated,service_role;

do $schedule$
declare
  previous_active boolean;
  scheduler_job bigint;
begin
  select active into previous_active from cron.job where jobname='download-queue-watchdog-v1';
  select cron.schedule('download-queue-watchdog-v1','*/5 * * * *',
    'select public.download_scheduler_tick();') into scheduler_job;
  -- Initial install is inactive. Enable only after the authenticated route passes
  -- negative checks; rerunning the migration preserves the existing active flag.
  perform cron.alter_job(scheduler_job,active:=coalesce(previous_active,false));
end
$schedule$;
