"""Durable, idempotent job consumer; privileged access is confined to this module.

Every database touch here goes through a ``worker_*`` SECURITY DEFINER
function. The credential this module holds has no direct table privileges at
all (see ``supabase/migrations/202609030003_worker_least_privilege.sql``), so
the set of things it can do is exactly the set of functions granted to it —
auditable by reading one migration rather than by trusting call sites.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import UUID
from vercel.queue import QueueClient, subscribe
from backend.cloud.gateway import Gateway
from backend.cloud.contracts import Preferences
from backend.cloud.engine import build_result, PARSER_VERSION
from backend.models import AnalysisResponse
from backend.plan_summary import summarize


# Each inline job allows 90s of parsing, and the whole sweep shares the engine's
# 300s ceiling with cleanup and account deletion.
INLINE_JOBS_PER_SWEEP=2

def queue():
    return QueueClient(region=os.environ.get('VERCEL_QUEUE_REGION','iad1'))

async def dispatch(job_id: str):
    # No credentials, document text, filenames or account information in the queue.
    return await queue().send('audit-analysis',{'job_id':str(UUID(job_id))})

async def parse_isolated(gateway, manifest):
    root=Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix='multi-major-') as directory:
        paths=[]
        for i,item in enumerate(manifest):
            data=await gateway.download(item['path'])
            if len(data)!=item['size']: raise ValueError('Uploaded file size changed. Upload the reports again.')
            p=Path(directory)/f'{i}.pdf';p.write_bytes(data);paths.append(str(p))
        # The child starts from a stripped environment so it inherits none of this
        # service's credentials. It still has to find its own imports, and on Vercel
        # the dependencies are vendored beside the application (/var/task/_vendor)
        # rather than installed into the interpreter, so a bare PYTHONPATH of the
        # project root cannot import pdfplumber and every report is rejected. Carry
        # this process's own search path instead; it holds no secrets.
        search=[str(root)]+[entry for entry in sys.path if entry not in ('','.',str(root))]
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'PYTHONPATH':os.pathsep.join(dict.fromkeys(search)),'PYTHONIOENCODING':'utf-8'}
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','backend.cloud.parse_process',*paths,cwd=root,env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try: output,diagnostic=await asyncio.wait_for(process.communicate(),timeout=45)
        except BaseException:
            if process.returncode is None: process.kill()
            await process.wait();raise
        if process.returncode or len(output)>2500000:
            # The child reports its own deployment faults in full and a document
            # fault by exception type only, so no report content reaches the log.
            print(json.dumps({'event':'parse_failed','returncode':process.returncode,'reason':diagnostic.decode('utf-8','replace').strip()[-500:]}))
            raise ValueError('Unable to interpret these reports safely. Use text-based Full Requirements DARS PDFs.')
        parsed=json.loads(output)
        if not isinstance(parsed,list): raise ValueError('Unsupported audit format.')
        return parsed

async def cleanup_job(gateway, job):
    # Validate all paths against the database record, never against queue input.
    prefix=f"{job['user_id']}/{job['id']}/"
    paths=[f['path'] for f in job['manifest']]
    if any(not p.startswith(prefix) or '..' in p for p in paths): raise ValueError('Invalid manifest.')
    await gateway.remove_objects(paths)
    settled=datetime.now(timezone.utc) >= datetime.fromisoformat(job['created_at'].replace('Z','+00:00')) + timedelta(hours=2, minutes=15)
    await gateway.rpc('worker_mark_clean',p_job=job['id'],p_done=settled)

def program_identity(data):
    return sorted((a.get('program_code') or a['name'],a.get('summary',{}).get('catalog_year') or '',a.get('campus','')) for a in data)

async def compatible_state(g,job,parsed):
    # Read only this job owner's recent plans, and only reuse an identical program/catalog set.
    plans=await g.rpc('worker_reusable_plans',p_user=job['user_id'],p_limit=20)
    for plan in plans or []:
        if not plan.get('state') or not plan.get('audit_id'): continue
        if program_identity(plan['data'])!=program_identity(parsed): continue
        from backend.cloud.contracts import SavePlan
        state=SavePlan(revision=1,state=plan['state']).state.model_dump()
        if plan.get('preferences')!=job['preferences']: state['term_settings']=[]
        return state
    return {}

async def process_job(job_id: str, gateway=None):
    job_id=str(UUID(job_id));g=gateway or Gateway(privileged=True)
    job=await g.rpc('worker_claim',p_job=job_id)
    if not job: return
    started=time.perf_counter()
    try:
        prefix=f"{job['user_id']}/{job['id']}/"
        if any(not f['path'].startswith(prefix) or '..' in f['path'] for f in job['manifest']): raise ValueError('Invalid upload manifest.')
        # Each stage is reported before it starts, so a student polling the job
        # sees which step is running rather than an unchanging 'processing'.
        # Progress reporting must never be able to fail the analysis itself.
        async def report(stage: str, progress: int):
            try: await g.rpc('worker_progress',p_job=job_id,p_stage=stage,p_progress=progress)
            except Exception: pass
        await report('Reading your reports',10)
        parsed=await asyncio.wait_for(parse_isolated(g,job['manifest']),timeout=90)
        await report('Matching your saved decisions',60)
        state=await compatible_state(g,job,parsed)
        await report('Building your semester map',75)
        result=AnalysisResponse.model_validate(build_result(parsed,Preferences.model_validate(job['preferences']),state)).model_dump()
        await report('Saving your map',95)
        await g.rpc('worker_finish',p_job=job_id,p_attempt=job['attempts'],p_data=parsed,p_result=result,p_parser=PARSER_VERSION,p_state=state,p_summary=summarize(result,job['preferences']))
    except (ValueError,asyncio.TimeoutError):
        await g.rpc('worker_fail',p_job=job_id,p_attempt=job['attempts'],p_error='The audit could not be interpreted within the safety limits. Export a text-based Full Requirements report and try again.',p_terminal=True)
    except Exception:
        await g.rpc('worker_fail',p_job=job_id,p_attempt=job['attempts'],p_error='Processing was interrupted. A retry has been scheduled.',p_terminal=False)
        raise
    finally:
        fresh=await g.rpc('worker_job',p_job=job_id)
        if fresh and fresh['status'] in ('completed','failed','cancelled'):
            try: await cleanup_job(g,fresh)
            except Exception: print(json.dumps({'event':'cleanup_pending','job_id':job_id}))
        print(json.dumps({'event':'analysis_attempt','job_id':job_id,'elapsed_ms':int((time.perf_counter()-started)*1000)}))

@subscribe(topic='audit-analysis',consumer_group='parser-v2',max_concurrency=10,max_attempts=3,retry_after=30)
async def consume_analysis(payload: dict[str, str]):
    await process_job(payload['job_id'])

async def maintenance():
    g=Gateway(privileged=True);await g.rpc('maintenance_expire')
    # At-least-once dispatch. Claim leases make duplicates harmless.
    jobs=await g.rpc('worker_queue',p_limit=100)
    for j in jobs:
        try: await dispatch(j['id'])
        except Exception: print(json.dumps({'event':'dispatch_pending','job_id':j['id']}))
    # Publishing only helps where Vercel Queues actually runs a subscriber. Where
    # it does not, the send still succeeds and the message is never consumed, so
    # a job would sit queued forever with nothing reporting a failure. Do the
    # oldest few here as the worker of last resort: worker_claim leases the job,
    # so a real consumer and this loop cannot both process one. Kept small
    # because the whole sweep shares one function timeout.
    processed=0
    for j in jobs[:INLINE_JOBS_PER_SWEEP]:
        try:
            await process_job(j['id'],g);processed+=1
        except Exception: print(json.dumps({'event':'inline_pending','job_id':j['id']}))
    dirty=await g.rpc('worker_dirty',p_limit=100)
    failed=0
    for j in dirty:
        try: await cleanup_job(g,j)
        except Exception: failed+=1
    # Deleted accounts leave only opaque upload paths until signed upload capabilities expire.
    tombstones=await g.rpc('worker_tombstones')
    for tombstone in tombstones:
        try:
            await g.remove_objects(tombstone['paths'])
            await g.rpc('worker_clear_tombstone',p_id=tombstone['id'])
        except Exception: failed+=1
    # Retry account deletion after transient storage/Auth failures.
    deleting=await g.rpc('worker_deleting_profiles',p_limit=20)
    for profile in deleting:
        try: await delete_account(profile['user_id'],g)
        except Exception: failed+=1
    print(json.dumps({'event':'maintenance','dispatches':len(jobs),'processed':processed,'cleanup_failures':failed}))
    return {'dispatches':len(jobs),'processed':processed,'cleanup_failures':failed}

async def delete_account(user_id: str, gateway=None):
    g=gateway or Gateway(privileged=True)
    user_id=str(UUID(user_id))
    if not await g.rpc('worker_is_deleting',p_user=user_id): raise ValueError('Account deletion must be requested by its owner.')
    offset=0
    while True:
        jobs=await g.rpc('worker_user_jobs',p_user=user_id,p_limit=100,p_offset=offset)
        for j in jobs: await cleanup_job(g,j)
        if len(jobs)<100: break
        offset+=100
    await g.request('DELETE','/auth/v1/admin/users/'+str(UUID(user_id)))
