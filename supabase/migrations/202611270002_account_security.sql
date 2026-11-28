-- Server-only account credentials, confirmation challenges and short deletion leases.
create schema if not exists account_private;
revoke all on schema account_private from public, anon, authenticated;
create table account_private.security (
  user_id uuid primary key references auth.users(id) on delete cascade,
  apple_subject text,
  encrypted_token jsonb,
  revoked_at timestamptz,
  credential_session text,
  credential_auth_at bigint,
  challenge_hash text,
  challenge_session text,
  challenge_expires timestamptz,
  lease_id uuid,
  lease_expires timestamptz,
  rate_started timestamptz not null default now(),
  rate_count integer not null default 0,
  constraint credential_binding check (
    (apple_subject is null and encrypted_token is null and revoked_at is null)
    or (apple_subject is not null and credential_session is not null and credential_auth_at is not null)
  )
);
alter table account_private.security enable row level security;
revoke all on account_private.security from public, anon, authenticated;

-- Only the Edge Function's server-side service role can call this RPC.
-- Every change locks one user's row; leases serialize requests across function instances.
create function public.account_security(p_user uuid, p_action text, p_data jsonb default '{}'::jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare r account_private.security%rowtype;
begin
  insert into account_private.security(user_id) values(p_user) on conflict do nothing;
  select * into strict r from account_private.security where user_id=p_user for update;
  if p_action='rate' then
    if r.rate_started < now()-interval '1 minute' then
      update account_private.security set rate_started=now(),rate_count=1 where user_id=p_user;
    elsif r.rate_count >= 12 then return jsonb_build_object('allowed',false);
    else update account_private.security set rate_count=rate_count+1 where user_id=p_user;
    end if;
    return jsonb_build_object('allowed',true);
  elsif p_action='read' then
    return jsonb_build_object('subject',r.apple_subject,'token',r.encrypted_token,'revoked',r.revoked_at is not null,'session',r.credential_session,'authAt',r.credential_auth_at);
  elsif p_action='save' then
    if r.lease_expires > now() then return null; end if;
    update account_private.security set apple_subject=p_data->>'subject',encrypted_token=p_data->'token',
      revoked_at=null,credential_session=p_data->>'session',credential_auth_at=(p_data->>'authAt')::bigint,
      challenge_hash=null,challenge_expires=null where user_id=p_user;
    return '{}'::jsonb;
  elsif p_action='prepare' then
    if r.lease_expires > now() then return null; end if;
    update account_private.security set challenge_hash=p_data->>'hash',challenge_session=p_data->>'session',
      challenge_expires=now()+interval '5 minutes' where user_id=p_user;
    return '{}'::jsonb;
  elsif p_action='begin' then
    if r.challenge_hash is null or r.challenge_hash is distinct from p_data->>'hash'
       or r.challenge_session is distinct from p_data->>'session'
       or r.challenge_expires<=now() or r.lease_expires>now() then return null; end if;
    update account_private.security set challenge_hash=null,challenge_expires=null,
      lease_id=(p_data->>'lease')::uuid,lease_expires=now()+interval '2 minutes' where user_id=p_user;
    return jsonb_build_object('subject',r.apple_subject,'token',r.encrypted_token,'revoked',r.revoked_at is not null,'session',r.credential_session,'authAt',r.credential_auth_at);
  elsif p_action='revoked' then
    if r.lease_id is distinct from (p_data->>'lease')::uuid or r.lease_expires<=now() then return null; end if;
    update account_private.security set revoked_at=now(),encrypted_token=null where user_id=p_user;
    return '{}'::jsonb;
  elsif p_action='release' then
    update account_private.security set lease_id=null,lease_expires=null
      where user_id=p_user and lease_id=(p_data->>'lease')::uuid;
    return '{}'::jsonb;
  end if;
  raise exception 'Unknown account-security action';
end;
$$;
revoke all on function public.account_security(uuid,text,jsonb) from public, anon, authenticated;
grant execute on function public.account_security(uuid,text,jsonb) to service_role;
