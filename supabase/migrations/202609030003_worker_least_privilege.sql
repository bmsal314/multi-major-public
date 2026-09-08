-- ORDERING: apply this ONLY with the matching backend deploy, never before it.
--
-- This migration is code-coupled. The final REVOKE removes the privileges the
-- *previous* release depends on: that worker performs eight direct table reads
-- and one direct PATCH. Applying it against an older deployment breaks job
-- processing and the maintenance sweep immediately, with 42501 permission
-- errors the student sees as an analysis that never finishes.
--
-- This happened once, on 2026-09-03, against staging. The guard below now
-- refuses the revoke unless the worker_* functions this release introduced are
-- all present, which is the closest a migration can get to checking that the
-- code shipped with it.
--
-- Scope the worker credential to the operations it actually performs.
--
-- The starting position was already better than the brief assumed: user calls
-- run as `authenticated` under RLS with SELECT-only grants, every write goes
-- through a SECURITY DEFINER RPC, and the privileged key is constructed in one
-- module (backend/cloud/worker.py). The real residual gap is narrower: that key
-- resolves to `service_role`, which both bypasses RLS and holds blanket DML on
-- every application table -- far more than the ten operations the worker makes.
--
-- Supabase's new-format secret key (`sb_secret_...`) is bound to `service_role`
-- and cannot be remapped to a custom Postgres role, and the GoTrue admin and
-- Storage APIs require that key regardless of any database role. A separate
-- login role is therefore not achievable on hosted Supabase. What *is*
-- achievable is removing the privilege that key carries: after this migration a
-- leaked worker key can invoke the audited functions below and nothing else --
-- it cannot read or write a single row of any table directly.

-- ---------------------------------------------------------------- job queue
create or replace function public.worker_queue(p_limit integer default 100)
returns jsonb language sql security definer set search_path='' as $$
 select coalesce(jsonb_agg(to_jsonb(j) order by j.created_at),'[]')
 from (select * from public.analysis_jobs
       where status in ('queued','processing')
       order by created_at limit least(greatest(p_limit,1),200)) j
$$;

create or replace function public.worker_dirty(p_limit integer default 100)
returns jsonb language sql security definer set search_path='' as $$
 select coalesce(jsonb_agg(to_jsonb(j)),'[]')
 from (select * from public.analysis_jobs
       where status in ('completed','failed','cancelled') and cleanup_done=false
       limit least(greatest(p_limit,1),200)) j
$$;

create or replace function public.worker_job(p_job uuid)
returns jsonb language sql security definer set search_path='' as $$
 select to_jsonb(j) from public.analysis_jobs j where j.id=p_job
$$;

create or replace function public.worker_mark_clean(p_job uuid, p_done boolean)
returns void language plpgsql security definer set search_path='' as $$
begin update public.analysis_jobs set cleanup_done=p_done where id=p_job; end $$;

-- ------------------------------------------------------- state reuse lookup
-- The program/catalog comparison stays in Python, where it already lives; this
-- only hands back that owner's recent plans with the audit each was built from.
create or replace function public.worker_reusable_plans(p_user uuid, p_limit integer default 20)
returns jsonb language sql security definer set search_path='' as $$
 select coalesce(jsonb_agg(jsonb_build_object(
   'state',p.state,'preferences',p.preferences,'audit_id',p.audit_id,'data',a.data)
   order by p.updated_at desc),'[]')
 from public.plans p join public.audits a
   on a.id=p.audit_id and a.user_id=p.user_id
 where p.user_id=p_user
 limit least(greatest(p_limit,1),50)
$$;

-- ------------------------------------------------------- account lifecycle
create or replace function public.worker_deleting_profiles(p_limit integer default 20)
returns jsonb language sql security definer set search_path='' as $$
 select coalesce(jsonb_agg(to_jsonb(p)),'[]')
 from (select * from public.profiles where deleting limit least(greatest(p_limit,1),100)) p
$$;

create or replace function public.worker_is_deleting(p_user uuid)
returns boolean language sql security definer set search_path='' as $$
 select coalesce((select deleting from public.profiles where user_id=p_user), false)
$$;

create or replace function public.worker_user_jobs(p_user uuid, p_limit integer default 100, p_offset integer default 0)
returns jsonb language sql security definer set search_path='' as $$
 select coalesce(jsonb_agg(to_jsonb(j) order by j.id),'[]')
 from (select * from public.analysis_jobs where user_id=p_user
       order by id limit least(greatest(p_limit,1),200) offset greatest(p_offset,0)) j
$$;

-- Only the worker credential may call any of these.
do $$ declare r record; begin
 for r in select p.oid::regprocedure signature from pg_proc p
   join pg_namespace n on n.oid=p.pronamespace
   where n.nspname='public' and p.proname in
   ('worker_queue','worker_dirty','worker_job','worker_mark_clean',
    'worker_reusable_plans','worker_deleting_profiles','worker_is_deleting',
    'worker_user_jobs') loop
  execute format('revoke all on function %s from public,anon,authenticated',r.signature);
  execute format('grant execute on function %s to service_role',r.signature);
 end loop;
end $$;


-- Refuse the revoke unless every replacement function exists. A partial apply
-- leaves the grants intact, which is the safe direction to fail in.
do $$
declare missing text;
begin
  select string_agg(name,', ') into missing from unnest(array[
    'worker_queue','worker_dirty','worker_job','worker_mark_clean',
    'worker_reusable_plans','worker_deleting_profiles','worker_is_deleting',
    'worker_user_jobs']) as name
  where not exists (
    select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname=name);
  if missing is not null then
    raise exception 'Refusing to revoke: missing replacement functions (%). Deploy the matching backend first.', missing;
  end if;
end $$;

-- The point of the exercise: the worker key loses direct table access entirely.
revoke all on public.profiles,public.analysis_jobs,public.audits,public.plans,
              public.plan_revisions,public.security_events from service_role;
