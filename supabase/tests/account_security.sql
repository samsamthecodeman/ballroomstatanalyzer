-- Isolated test database only; run after both migrations and profiles.sql.
set role authenticated;
do $$ begin
  begin
    perform public.account_security('11111111-1111-1111-1111-111111111111','read');
    raise exception 'Authenticated caller can access service-only RPC';
  exception when insufficient_privilege then null; end;
  begin
    perform * from account_private.security;
    raise exception 'Authenticated caller can read token storage';
  exception when insufficient_privilege then null; end;
end $$;
reset role;
set role anon;
do $$ begin
  begin
    perform public.account_security('11111111-1111-1111-1111-111111111111','read');
    raise exception 'Anonymous caller can access service-only RPC';
  exception when insufficient_privilege then null; end;
end $$;
reset role;
set role service_role;
do $$
declare a uuid='11111111-1111-1111-1111-111111111111'; b uuid='22222222-2222-2222-2222-222222222222';
  lease uuid='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'; value jsonb;
begin
  perform public.account_security(a,'save','{"subject":"apple-subject","session":"session-a","authAt":1000000,"token":{"ciphertext":"test-envelope"}}');
  perform public.account_security(a,'prepare','{"hash":"expected","session":"session-a"}');
  if public.account_security(b,'begin',jsonb_build_object('hash','expected','session','session-a','lease',lease)) is not null then raise exception 'Other user consumed confirmation'; end if;
  if public.account_security(a,'begin',jsonb_build_object('hash','wrong','session','session-a','lease',lease)) is not null then raise exception 'Wrong confirmation accepted'; end if;
  if public.account_security(a,'begin',jsonb_build_object('session','session-a','lease',lease)) is not null then raise exception 'Missing confirmation accepted'; end if;
  if public.account_security(a,'begin',jsonb_build_object('hash','expected','session','other-session','lease',lease)) is not null then raise exception 'Other session consumed confirmation'; end if;
  value=public.account_security(a,'begin',jsonb_build_object('hash','expected','session','session-a','lease',lease));
  if value->>'subject'<>'apple-subject' then raise exception 'Missing token state'; end if;
  if public.account_security(a,'save','{"subject":"other","token":{}}') is not null then raise exception 'Credential changed during deletion lease'; end if;
  if public.account_security(a,'prepare','{"hash":"new","session":"session-a"}') is not null then raise exception 'Concurrent deletion allowed'; end if;
  if public.account_security(a,'revoked',jsonb_build_object('lease','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')) is not null then raise exception 'Wrong lease wrote revocation receipt'; end if;
  perform public.account_security(a,'revoked',jsonb_build_object('lease',lease));
  value=public.account_security(a,'read');
  if not (value->>'revoked')::boolean or value->'token'<>'null'::jsonb then raise exception 'Credential was not erased after revocation'; end if;
  perform public.account_security(a,'release',jsonb_build_object('lease',lease));
  if public.account_security(a,'begin',jsonb_build_object('hash','expected','session','session-a','lease',lease)) is not null then raise exception 'Replayed confirmation accepted'; end if;
  for i in 1..12 loop
    if not (public.account_security(a,'rate')->>'allowed')::boolean then raise exception 'Premature rate limit'; end if;
  end loop;
  if (public.account_security(a,'rate')->>'allowed')::boolean then raise exception 'Rate limit bypass'; end if;
end $$;
reset role;
-- Expiry and referential cleanup are tested against synthetic users in this database only.
update account_private.security set challenge_hash='expired',challenge_session='session-a',challenge_expires=now()-interval '1 second'
where user_id='11111111-1111-1111-1111-111111111111';
set role service_role;
do $$ begin
  if public.account_security('11111111-1111-1111-1111-111111111111','begin','{"hash":"expired","session":"session-a","lease":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}') is not null then raise exception 'Expired confirmation accepted'; end if;
end $$;
reset role;
delete from auth.users where id='11111111-1111-1111-1111-111111111111';
do $$ begin
  if exists(select 1 from account_private.security where user_id='11111111-1111-1111-1111-111111111111') then raise exception 'Private credential row did not cascade'; end if;
  if exists(select 1 from public.profiles where id='11111111-1111-1111-1111-111111111111') then raise exception 'Saved profile did not cascade'; end if;
end $$;
select 'PASS: private vault, service-only access, confirmation/lease isolation, rate limiting, expiry and cascading cleanup' as result;
