-- Visible progress for long analyses.
--
-- Parsing several DARS reports and rebuilding a map runs well past the two
-- seconds where a spinner stops being honest, and the job table only ever said
-- 'processing'. A student watching an unchanging status cannot tell a slow parse
-- from a stuck one. There is no realtime channel in this stack — the client
-- already polls GET /analyses every three seconds — so progress is recorded on
-- the job row and read by that same poll.

alter table public.analysis_jobs add column if not exists stage text;
alter table public.analysis_jobs add column if not exists progress smallint not null default 0;

-- Only the worker credential may report progress, on a job it currently holds.
create or replace function public.worker_progress(p_job uuid, p_stage text, p_progress integer)
returns void language plpgsql security definer set search_path='' as $$
begin
 update public.analysis_jobs
 set stage=left(p_stage,60), progress=greatest(0,least(100,p_progress))
 where id=p_job and status='processing';
end $$;

revoke all on function public.worker_progress(uuid,text,integer) from public,anon,authenticated;
grant execute on function public.worker_progress(uuid,text,integer) to service_role;

-- A finished job must not keep reporting a mid-flight stage.
create or replace function public.worker_finish(p_job uuid,p_attempt integer,p_data jsonb,p_result jsonb,p_parser text,p_state jsonb default '{}') returns uuid language plpgsql security definer set search_path='' as $$
declare j public.analysis_jobs; a uuid; p uuid; begin
 select * into j from public.analysis_jobs where id=p_job for update;
 if not found or j.status<>'processing' or j.attempts<>p_attempt or j.expires_at<=now() or exists(select 1 from public.profiles where user_id=j.user_id and deleting) then return null; end if;
 if pg_column_size(p_result)>2500000 or pg_column_size(p_data)>2500000 then raise sqlstate 'PT422'; end if;
 insert into public.audits(user_id,job_id,data,parser_version) values(j.user_id,j.id,p_data,p_parser) returning id into a;
 insert into public.plans(user_id,audit_id,name,preferences,result,state) values(j.user_id,a,'My semester map',j.preferences,p_result,p_state) returning id into p;
 insert into public.plan_revisions(user_id,plan_id,revision,state,preferences) values(j.user_id,p,1,p_state,j.preferences);
 update public.analysis_jobs set status='completed',plan_id=p,lease_until=null,stage='Ready',progress=100 where id=p_job;
 return p;
end $$;
grant execute on function public.worker_finish(uuid,integer,jsonb,jsonb,text,jsonb) to service_role;
