-- Run after bootstrap.sql and the migration in an isolated database.
set role authenticated;
set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
insert into public.profiles values ('11111111-1111-1111-1111-111111111111', 'Dancer One', 10062);
do $$ begin
  if (select count(*) from public.profiles) <> 1 then raise exception 'Owner cannot see profile'; end if;
end $$;
set request.jwt.claim.sub = '22222222-2222-2222-2222-222222222222';
do $$ begin
  if (select count(*) from public.profiles) <> 0 then raise exception 'Cross-account profile leak'; end if;
  update public.profiles set dancer_name = 'Wrong owner';
  if found then raise exception 'Cross-account update allowed'; end if;
  begin
    insert into public.profiles values ('11111111-1111-1111-1111-111111111111', 'Wrong owner', null);
    raise exception 'Cross-account insert allowed';
  exception when insufficient_privilege then null;
  end;
end $$;
insert into public.profiles values ('22222222-2222-2222-2222-222222222222', 'Dancer Two', null);
reset role;
set role anon;
do $$ begin
  begin
    perform * from public.profiles;
    raise exception 'Anonymous access allowed';
  exception when insufficient_privilege then null;
  end;
end $$;
reset role;
select 'PASS: owner access, cross-account isolation, anonymous denial' as result;
