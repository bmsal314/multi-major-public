-- At-a-glance metadata for the permutations dashboard.
--
-- The plan list deliberately does not return `result`: a saved result runs to
-- megabytes and the dashboard would ship all of them to render a few numbers.
-- A small summary is written beside the result whenever a plan is created or
-- saved, so the dashboard can compare permutations without loading any of them.

alter table public.plans add column if not exists summary jsonb not null default '{}';

create or replace function public.create_plan(p_audit uuid,p_name text,p_preferences jsonb,p_result jsonb,p_summary jsonb default '{}') returns jsonb language plpgsql security definer set search_path='' as $$
declare u uuid:=private.require_owner(); p public.plans; begin
 if not exists(select 1 from public.audits where id=p_audit and user_id=u) then raise sqlstate 'PT404'; end if;
 if not private.consume('plan:'||u,30,3600) then raise sqlstate 'PT429'; end if;
 if pg_column_size(p_result)>2500000 or pg_column_size(p_preferences)>20000 or pg_column_size(p_summary)>20000 then raise sqlstate 'PT422'; end if;
 insert into public.plans(user_id,audit_id,name,preferences,result,summary) values(u,p_audit,p_name,p_preferences,p_result,p_summary) returning * into p;
 insert into public.plan_revisions(user_id,plan_id,revision,state,preferences) values(u,p.id,1,'{}',p_preferences);
 return to_jsonb(p);
end $$;

create or replace function public.save_plan(p_plan uuid,p_revision integer,p_state jsonb,p_result jsonb,p_name text default null,p_summary jsonb default null) returns jsonb language plpgsql security definer set search_path='' as $$
declare p public.plans; begin
 select * into p from public.plans where id=p_plan and user_id=private.require_owner() for update;
 if not found then raise sqlstate 'PT404'; end if;
 if p.revision<>p_revision then raise sqlstate 'PT409'; end if;
 if pg_column_size(p_state)>524288 or pg_column_size(p_result)>2500000 then raise sqlstate 'PT422'; end if;
 update public.plans set state=p_state,result=p_result,name=coalesce(p_name,name),
   summary=coalesce(p_summary,summary),revision=revision+1,updated_at=now()
 where id=p.id returning * into p;
 insert into public.plan_revisions(user_id,plan_id,revision,state,preferences) values(p.user_id,p.id,p.revision,p.state,p.preferences);
 return to_jsonb(p);
end $$;

-- The worker writes the first plan for a job, so it carries a summary too.
create or replace function public.worker_finish(p_job uuid,p_attempt integer,p_data jsonb,p_result jsonb,p_parser text,p_state jsonb default '{}',p_summary jsonb default '{}') returns uuid language plpgsql security definer set search_path='' as $$
declare j public.analysis_jobs; a uuid; p uuid; begin
 select * into j from public.analysis_jobs where id=p_job for update;
 if not found or j.status<>'processing' or j.attempts<>p_attempt or j.expires_at<=now() or exists(select 1 from public.profiles where user_id=j.user_id and deleting) then return null; end if;
 if pg_column_size(p_result)>2500000 or pg_column_size(p_data)>2500000 then raise sqlstate 'PT422'; end if;
 insert into public.audits(user_id,job_id,data,parser_version) values(j.user_id,j.id,p_data,p_parser) returning id into a;
 insert into public.plans(user_id,audit_id,name,preferences,result,state,summary) values(j.user_id,a,'My semester map',j.preferences,p_result,p_state,p_summary) returning id into p;
 insert into public.plan_revisions(user_id,plan_id,revision,state,preferences) values(j.user_id,p,1,p_state,j.preferences);
 update public.analysis_jobs set status='completed',plan_id=p,lease_until=null,stage='Ready',progress=100 where id=p_job;
 return p;
end $$;

revoke all on function public.create_plan(uuid,text,jsonb,jsonb,jsonb) from public,anon;
grant execute on function public.create_plan(uuid,text,jsonb,jsonb,jsonb) to authenticated;
revoke all on function public.save_plan(uuid,integer,jsonb,jsonb,text,jsonb) from public,anon;
grant execute on function public.save_plan(uuid,integer,jsonb,jsonb,text,jsonb) to authenticated;
revoke all on function public.worker_finish(uuid,integer,jsonb,jsonb,text,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.worker_finish(uuid,integer,jsonb,jsonb,text,jsonb,jsonb) to service_role;

-- Adding p_summary created a *second* overload rather than replacing the first,
-- so create_plan and save_plan each existed twice and PostgREST could resolve a
-- call to the older signature — silently skipping the summary the permutations
-- dashboard reads. Drop the superseded ones.
drop function if exists public.create_plan(uuid, text, jsonb, jsonb);
drop function if exists public.save_plan(uuid, integer, jsonb, jsonb, text);
drop function if exists public.worker_finish(uuid, integer, jsonb, jsonb, text, jsonb);
