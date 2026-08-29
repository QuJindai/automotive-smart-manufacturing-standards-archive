-- Keep the shared Google OAuth state alive long enough for mobile account
-- selection and consent. The state remains high-entropy and one-time use.
create or replace function public.begin_gemini_notebook_oauth_attempt(p_state_hash text)
returns table(attempt_version bigint)
language sql
set search_path to ''
as $function$
  update public.gemini_notebook_connector_config as config
  set
    oauth_attempt_version = config.oauth_attempt_version + 1,
    oauth_state_nonce = p_state_hash,
    oauth_state_expires_at = now() + interval '60 minutes',
    updated_at = now()
  where config.id = 'default'
    and p_state_hash ~ '^[0-9a-f]{64}$'
  returning config.oauth_attempt_version;
$function$;
