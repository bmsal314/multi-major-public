-- Run only against a dedicated Multi-Major project. All ownership is derived from auth.uid().
create extension if not exists pgcrypto;
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table public.profiles (
 user_id uuid primary key references auth.users(id) on delete cascade,
 preferences jsonb not null default '{}', deleting boolean not null default false,
 created_at timestamptz not null default now()
);
create table public.analysis_jobs (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(user_id) on delete cascade,
 status text not null default 'awaiting_upload' check (status in ('awaiting_upload','queued','processing','completed','failed','cancelled')),
 manifest jsonb not null, preferences jsonb not null, created_at timestamptz not null default now(),
 expires_at timestamptz not null default now()+interval '24 hours', lease_until timestamptz,
 attempts integer not null default 0, dispatched_at timestamptz, error text, plan_id uuid,
 cleanup_done boolean not null default false, unique(user_id,id)
);
create table public.audits (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(user_id) on delete cascade,
 job_id uuid not null unique, data jsonb not null, parser_version text not null,
 created_at timestamptz not null default now(), unique(user_id,id),
 foreign key(user_id,job_id) references public.analysis_jobs(user_id,id) on delete cascade
);
create table public.plans (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(user_id) on delete cascade,
 audit_id uuid not null, name text not null check(length(name) between 1 and 120),
 preferences jsonb not null, result jsonb not null, state jsonb not null default '{}',
 revision integer not null default 1, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(user_id,id), foreign key(user_id,audit_id) references public.audits(user_id,id) on delete cascade
);
create table public.plan_revisions (
 user_id uuid not null, plan_id uuid not null, revision integer not null,
 state jsonb not null, preferences jsonb not null, created_at timestamptz not null default now(),
 primary key(plan_id,revision), foreign key(user_id,plan_id) references public.plans(user_id,id) on delete cascade
);
create table public.security_events (
 id bigint generated always as identity primary key, user_id uuid references public.profiles(user_id) on delete cascade,
 event text not null, created_at timestamptz not null default now()
);
create table private.rate_limits (
 key text primary key, hits integer not null, reset_at timestamptz not null
);
alter table private.rate_limits enable row level security;

create index on public.analysis_jobs(user_id,created_at desc);
create index on public.analysis_jobs(status,lease_until);
create index on public.audits(user_id,created_at desc);
create index on public.plans(user_id,updated_at desc);
create index on public.plan_revisions(user_id,plan_id);
create index on public.security_events(user_id,created_at desc);

-- No application table is writable merely because a JWT exists.
do $$ declare t text; begin
 foreach t in array array['profiles','analysis_jobs','audits','plans','plan_revisions','security_events'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('revoke all on public.%I from anon, authenticated',t);
  execute format('grant select on public.%I to authenticated',t);
  execute format('create policy owner_read on public.%I for select to authenticated using ((select auth.uid()) = user_id)',t);
 end loop;
end $$;
-- Direct mutations are intentionally unavailable; RPCs enforce invariants atomically.

create function private.require_owner() returns uuid language plpgsql security definer set search_path='' as $$
declare u uuid := auth.uid(); begin
 if u is null then raise insufficient_privilege; end if;
 if exists(select 1 from public.profiles where user_id=u and deleting) then raise insufficient_privilege; end if;
 return u;
end $$;
create function private.consume(k text, lim integer, seconds integer) returns boolean language plpgsql security definer set search_path='' as $$
declare n integer; begin
 insert into private.rate_limits as r values(k,1,now()+make_interval(secs=>seconds))
 on conflict(key) do update set hits=case when r.reset_at<=now() then 1 else r.hits+1 end,
 reset_at=case when r.reset_at<=now() then now()+make_interval(secs=>seconds) else r.reset_at end returning hits into n;
 return n<=lim;
end $$;

create function public.ensure_profile() returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=private.require_owner(); p public.profiles; begin
 insert into public.profiles(user_id) values(u) on conflict do nothing;
 select * into p from public.profiles where user_id=u;
 return to_jsonb(p);
end $$;
create function public.update_preferences(p_preferences jsonb) returns void language plpgsql security definer set search_path='' as $$
begin
 if pg_column_size(p_preferences)>20000 then raise sqlstate 'PT422'; end if;
 update public.profiles set preferences=p_preferences where user_id=private.require_owner();
end $$;

create function public.init_upload(p_sizes jsonb,p_preferences jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=private.require_owner(); j uuid:=gen_random_uuid(); files jsonb; total bigint; begin
 perform 1 from public.profiles where user_id=u for update;
 if not found then raise sqlstate 'PT422'; end if;
 if jsonb_array_length(p_sizes) not between 1 and 8 then raise sqlstate 'PT422'; end if;
 select sum(value::bigint) into total from jsonb_array_elements_text(p_sizes);
 if total>104857600 or exists(select 1 from jsonb_array_elements_text(p_sizes) where value::bigint not between 5 and 26214400) then raise sqlstate 'PT422'; end if;
 if pg_column_size(p_preferences)>20000 then raise sqlstate 'PT422'; end if;
 if exists(select 1 from public.analysis_jobs where user_id=u and status in ('awaiting_upload','queued','processing') and expires_at>now()) then raise sqlstate 'PT429'; end if;
 if not private.consume('upload-hour:'||u,5,3600) or not private.consume('upload-day:'||u,20,86400) then raise sqlstate 'PT429'; end if;
 select jsonb_agg(jsonb_build_object('path',u::text||'/'||j::text||'/'||ordinality::text||'.pdf','size',value::bigint)) into files from jsonb_array_elements_text(p_sizes) with ordinality;
 insert into public.analysis_jobs(id,user_id,manifest,preferences) values(j,u,files,p_preferences);
 return jsonb_build_object('id',j,'manifest',files);
end $$;

create function public.enqueue_analysis(p_job uuid) returns void language plpgsql security definer set search_path='' as $$
declare j public.analysis_jobs; f jsonb; begin
 select * into j from public.analysis_jobs where id=p_job and user_id=private.require_owner() for update;
 if not found then raise sqlstate 'PT404'; end if;
 if j.status in ('queued','processing','completed') then return; end if;
 if j.status<>'awaiting_upload' or j.expires_at<=now() then raise sqlstate 'PT422'; end if;
 for f in select * from jsonb_array_elements(j.manifest) loop
  if not exists(select 1 from storage.objects where bucket_id='audit-uploads' and name=f->>'path' and (metadata->>'size')::bigint=(f->>'size')::bigint) then raise sqlstate 'PT422'; end if;
 end loop;
 update public.analysis_jobs set status='queued' where id=j.id;
end $$;

create function public.save_plan(p_plan uuid,p_revision integer,p_state jsonb,p_result jsonb,p_name text default null) returns jsonb language plpgsql security definer set search_path='' as $$
declare p public.plans; begin
 select * into p from public.plans where id=p_plan and user_id=private.require_owner() for update;
 if not found then raise sqlstate 'PT404'; end if;
 if p.revision<>p_revision then raise sqlstate 'PT409'; end if;
 if pg_column_size(p_state)>524288 or pg_column_size(p_result)>2500000 then raise sqlstate 'PT422'; end if;
 update public.plans set state=p_state,result=p_result,name=coalesce(p_name,name),revision=revision+1,updated_at=now() where id=p.id returning * into p;
 insert into public.plan_revisions(user_id,plan_id,revision,state,preferences) values(p.user_id,p.id,p.revision,p.state,p.preferences);
 return to_jsonb(p);
end $$;
create function public.create_plan(p_audit uuid,p_name text,p_preferences jsonb,p_result jsonb) returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=private.require_owner(); p public.plans; begin
 if not exists(select 1 from public.audits where id=p_audit and user_id=u) then raise sqlstate 'PT404'; end if;
 if not private.consume('plan:'||u,30,3600) then raise sqlstate 'PT429'; end if;
 if pg_column_size(p_result)>2500000 or pg_column_size(p_preferences)>20000 then raise sqlstate 'PT422'; end if;
 insert into public.plans(user_id,audit_id,name,preferences,result) values(u,p_audit,p_name,p_preferences,p_result) returning * into p;
 insert into public.plan_revisions(user_id,plan_id,revision,state,preferences) values(u,p.id,1,'{}',p_preferences);
 return to_jsonb(p);
end $$;
create function public.delete_item(p_kind text,p_id uuid) returns void language plpgsql security definer set search_path='' as $$
declare u uuid:=private.require_owner(); begin
 if p_kind='plan' then delete from public.plans where id=p_id and user_id=u;
 elsif p_kind='audit' then
  update public.analysis_jobs set cleanup_done=false,plan_id=null where user_id=u and id=(select job_id from public.audits where id=p_id and user_id=u);
  delete from public.audits where id=p_id and user_id=u;
 else raise sqlstate 'PT422'; end if;
end $$;
create function public.cancel_job(p_job uuid) returns void language plpgsql security definer set search_path='' as $$
begin update public.analysis_jobs set status='cancelled' where id=p_job and user_id=private.require_owner() and status in ('awaiting_upload','queued','processing'); end $$;
create function public.begin_account_deletion() returns void language plpgsql security definer set search_path='' as $$
begin
 update public.profiles set deleting=true where user_id=auth.uid();
 update public.analysis_jobs set status='cancelled' where user_id=auth.uid() and status in ('awaiting_upload','queued','processing');
end $$;

-- Only the queue worker/maintenance credential can invoke lifecycle RPCs.
create function public.worker_claim(p_job uuid) returns jsonb language plpgsql security definer set search_path='' as $$
declare j public.analysis_jobs; begin
 select * into j from public.analysis_jobs where id=p_job for update;
 if not found or j.status not in ('queued','processing') or j.expires_at<=now() or j.attempts>=3 or (j.status='processing' and j.lease_until>now()) then return null; end if;
 if exists(select 1 from public.profiles where user_id=j.user_id and deleting) then return null; end if;
 update public.analysis_jobs set status='processing',attempts=attempts+1,lease_until=now()+interval '5 minutes' where id=p_job returning * into j;
 return to_jsonb(j);
end $$;
create function public.worker_finish(p_job uuid,p_attempt integer,p_data jsonb,p_result jsonb,p_parser text,p_state jsonb default '{}') returns uuid language plpgsql security definer set search_path='' as $$
declare j public.analysis_jobs; a uuid; p uuid; begin
 select * into j from public.analysis_jobs where id=p_job for update;
 if not found or j.status<>'processing' or j.attempts<>p_attempt or j.expires_at<=now() or exists(select 1 from public.profiles where user_id=j.user_id and deleting) then return null; end if;
 if pg_column_size(p_result)>2500000 or pg_column_size(p_data)>2500000 then raise sqlstate 'PT422'; end if;
 insert into public.audits(user_id,job_id,data,parser_version) values(j.user_id,j.id,p_data,p_parser) returning id into a;
 insert into public.plans(user_id,audit_id,name,preferences,result,state) values(j.user_id,a,'My semester map',j.preferences,p_result,p_state) returning id into p;
 insert into public.plan_revisions(user_id,plan_id,revision,state,preferences) values(j.user_id,p,1,p_state,j.preferences);
 update public.analysis_jobs set status='completed',plan_id=p,lease_until=null where id=p_job;
 return p;
end $$;
create function public.worker_fail(p_job uuid,p_attempt integer,p_error text,p_terminal boolean) returns void language plpgsql security definer set search_path='' as $$
begin update public.analysis_jobs set status=case when p_terminal or attempts>=3 then 'failed' else 'queued' end,
 error=left(p_error,300),lease_until=null where id=p_job and status='processing' and attempts=p_attempt; end $$;
create function public.auth_rate_limit(p_key text,p_scope text default 'ip') returns boolean language sql security definer set search_path='' as $$ select case when p_scope='ip' then private.consume('auth-ip:'||p_key,120,60) when p_scope='address' then private.consume('auth-address:'||p_key,10,900) else false end $$;
create function public.maintenance_expire() returns void language plpgsql security definer set search_path='' as $$
begin
 update public.analysis_jobs set status='failed',error='Processing expired. Please upload your reports again.' where status in ('awaiting_upload','queued','processing') and (expires_at<=now() or (attempts>=3 and lease_until<now()));
 delete from private.rate_limits where reset_at<now()-interval '1 day';
 delete from public.security_events where created_at<now()-interval '30 days';
end $$;

-- Remove PostgreSQL's default PUBLIC execution grant on ALL our functions.
do $$ declare r record; begin
 for r in select p.oid::regprocedure signature,p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname in
 ('ensure_profile','update_preferences','init_upload','enqueue_analysis','save_plan','create_plan','delete_item','cancel_job','begin_account_deletion','worker_claim','worker_finish','worker_fail','auth_rate_limit','maintenance_expire') loop
  execute format('revoke all on function %s from public,anon,authenticated',r.signature);
  if r.proname like 'worker_%' or r.proname in ('auth_rate_limit','maintenance_expire') then
   execute format('grant execute on function %s to service_role',r.signature);
  else execute format('grant execute on function %s to authenticated',r.signature); end if;
 end loop;
end $$;
revoke all on all functions in schema private from public,anon,authenticated;
grant all on public.profiles,public.analysis_jobs,public.audits,public.plans,public.plan_revisions,public.security_events to service_role;
grant usage,select on all sequences in schema public to service_role;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('audit-uploads','audit-uploads',false,26214400,array['application/pdf']) on conflict(id) do update set public=false,file_size_limit=26214400,allowed_mime_types=array['application/pdf'];
create policy audit_upload_insert on storage.objects for insert to authenticated with check(
 bucket_id='audit-uploads' and (storage.foldername(name))[1]=(select auth.uid())::text
 and exists(select 1 from public.analysis_jobs j where j.user_id=(select auth.uid()) and j.status='awaiting_upload' and j.expires_at>now()
 and exists(select 1 from jsonb_array_elements(j.manifest) f where f->>'path'=name))
);
-- No user SELECT/UPDATE policy: originals cannot be browsed, served, overwritten or reused.
create policy audit_upload_delete on storage.objects for delete to authenticated using(bucket_id='audit-uploads' and (storage.foldername(name))[1]=(select auth.uid())::text);

-- Routine API work is distributed-rate-limited in the same user context.
create function public.request_budget() returns void language plpgsql security definer set search_path='' as $$
begin
 if not private.consume('request:'||private.require_owner(),300,60) then raise sqlstate 'PT429'; end if;
end $$;
revoke all on function public.request_budget() from public,anon;
grant execute on function public.request_budget() to authenticated;

-- Storage upload signatures live for two hours. Deleting the object does not revoke
-- its signature, so preserve ONLY opaque paths and repeatedly delete until expiry.
create table private.upload_tombstones(id uuid primary key,paths jsonb not null,expires_at timestamptz not null);
alter table private.upload_tombstones enable row level security;
revoke all on private.upload_tombstones from public,anon,authenticated;
create function private.remember_upload_paths() returns trigger language plpgsql security definer set search_path='' as $$
begin
 insert into private.upload_tombstones(id,paths,expires_at)
 select old.id,jsonb_agg(f->>'path'),greatest(now(),old.created_at+interval '2 hours 15 minutes') from jsonb_array_elements(old.manifest) f
 on conflict(id) do nothing;
 return old;
end $$;
create trigger remember_upload_paths before delete on public.analysis_jobs for each row execute function private.remember_upload_paths();
create function public.worker_tombstones() returns jsonb language sql security definer set search_path='' as $$
 select coalesce(jsonb_agg(t),'[]') from (select * from private.upload_tombstones order by expires_at limit 100) t
$$;
create function public.worker_clear_tombstone(p_id uuid) returns void language sql security definer set search_path='' as $$
 delete from private.upload_tombstones where id=p_id and expires_at<=now()
$$;
revoke all on function private.remember_upload_paths() from public,anon,authenticated;
revoke all on function public.worker_tombstones(),public.worker_clear_tombstone(uuid) from public,anon,authenticated;
grant execute on function public.worker_tombstones(),public.worker_clear_tombstone(uuid) to service_role;
