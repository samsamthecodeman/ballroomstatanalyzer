-- Apply in your Supabase project's SQL Editor, or with `supabase db push`.
create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  dancer_name text not null check (char_length(dancer_name) between 1 and 100),
  dancer_aid bigint check (dancer_aid is null or dancer_aid > 0)
);
alter table public.profiles enable row level security;
revoke all on public.profiles from anon;
grant select, insert, update, delete on public.profiles to authenticated;
create policy "Read own saved dancer" on public.profiles for select to authenticated using ((select auth.uid()) = id);
create policy "Save own dancer" on public.profiles for insert to authenticated with check ((select auth.uid()) = id);
create policy "Update own dancer" on public.profiles for update to authenticated using ((select auth.uid()) = id) with check ((select auth.uid()) = id);
create policy "Remove own saved dancer" on public.profiles for delete to authenticated using ((select auth.uid()) = id);
