"""Private Vercel service. No anonymous parsing, filesystem audits, or shutdown routes."""
from __future__ import annotations
import asyncio
import hmac
import os
from uuid import UUID
from typing import Literal
from fastapi import Query
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from backend.cloud.contracts import UploadRequest, UploadTicket, StartAnalysis, SavePlan, CreatePlan, ProfileUpdate, Preferences
from backend.cloud.gateway import Gateway
from backend.cloud.engine import build_result
from backend.models import AnalysisResponse
from backend.plan_summary import summarize

app=FastAPI(title='Multi-Major internal API',version='2.0.0',docs_url=None,redoc_url=None,openapi_url=None)

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # FastAPI's default validation output can echo a student's input.
    return JSONResponse(status_code=422,content={'detail':'Check the submitted fields, file limits and planning terms.'})

@app.middleware('http')
async def internal_boundary(request: Request,call_next):
    secret=os.environ.get('INTERNAL_API_SECRET','')
    if len(secret)<32 or not hmac.compare_digest(request.headers.get('x-internal-secret',''),secret):
        return JSONResponse(status_code=403,content={'detail':'Private service.'})
    # Bound streamed bodies too; a client can omit or forge Content-Length.
    size=0; chunks=[]
    async for chunk in request.stream():
        size+=len(chunk)
        if size>1048576: return JSONResponse(status_code=413,content={'detail':'Request too large.'})
        chunks.append(chunk)
    request._body=b''.join(chunks)
    response=await call_next(request);response.headers['Cache-Control']='private, no-store';return response

async def user(authorization: str=Header(default='')):
    if not authorization.startswith('Bearer '): raise HTTPException(401,'Sign in to continue.')
    g=Gateway(authorization[7:]);account=await g.request('GET','/auth/v1/user')
    if not account.get('email_confirmed_at'): raise HTTPException(403,'Confirm your email first.')
    profile=await g.rpc('ensure_profile')
    await g.rpc('request_budget')
    return g,account,profile

@app.get('/health')
async def health(): return {'status':'ok'}

@app.get('/profile')
async def profile(ctx=Depends(user)): return ctx[2]
@app.put('/profile')
async def update_profile(payload: ProfileUpdate,ctx=Depends(user)):
    await ctx[0].rpc('update_preferences',p_preferences=payload.preferences.model_dump());return {'ok':True}

@app.post('/uploads',response_model=UploadTicket)
async def uploads(payload: UploadRequest,ctx=Depends(user)):
    g,account,_=ctx
    j=await g.rpc('init_upload',p_sizes=[f.size for f in payload.files],p_preferences=payload.preferences.model_dump())
    tickets=[]
    for f in j['manifest']:
        path=f['path']
        # Storage signals overwrite through the `x-upsert` header, not the body.
        # Omitting it is what makes the signature single-use for a new object.
        ticket=await g.request('POST','/storage/v1/object/upload/sign/audit-uploads/'+path,body={})
        # Storage returns a relative signed URL. Only accept the project's own origin.
        url=ticket.get('url') or ticket.get('signedURL')
        if not url: raise HTTPException(502,'Could not authorize upload.')
        url=(g.url+'/storage/v1'+url) if url.startswith('/object/') else (g.url+url if url.startswith('/') else url)
        if not url.startswith(g.url+'/storage/v1/'): raise HTTPException(502,'Invalid upload destination.')
        tickets.append({'url':url,'path':path})
    return {'job_id':j['id'],'uploads':tickets}

@app.post('/analyses',status_code=202)
async def analyze(payload: StartAnalysis,ctx=Depends(user)):
    # enqueue_analysis is owner-scoped, so a job belonging to anyone else is
    # refused here and never reaches the privileged worker below.
    g=ctx[0];job=str(payload.job_id);await g.rpc('enqueue_analysis',p_job=job)
    from backend.cloud.worker import dispatch, process_job
    try: await dispatch(job)
    except Exception: pass # Persistent queued record is the outbox; maintenance retries.
    # Queues accept the message wherever the SDK can reach them but only deliver it
    # where a subscriber is provisioned, so on a plan without Queues the job would
    # sit 'queued' until the next sweep. Reading a batch of reports takes about a
    # second, so do it in this request and let the student see the result now.
    # worker_claim leases the job, so a real consumer cannot also run it.
    try: await asyncio.wait_for(process_job(job),timeout=40)
    except Exception: pass # Still queued or leased; the sweep and the queue retry.
    record=await g.one('analysis_jobs',payload.job_id,select='id,status,error,plan_id,stage,progress')
    return {'job_id':job,'status':record['status'],'error':record['error'],'plan_id':record['plan_id'],'stage':record.get('stage'),'progress':record.get('progress',0)}

@app.get('/analyses')
async def jobs(ctx=Depends(user)):
    return await ctx[0].rows('analysis_jobs',select='id,status,created_at,error,plan_id,stage,progress',order='created_at.desc',limit='20')
@app.get('/analyses/{job_id}')
async def job(job_id: UUID,ctx=Depends(user)):
    return await ctx[0].one('analysis_jobs',job_id,select='id,status,created_at,error,plan_id,stage,progress')
@app.delete('/analyses/{job_id}')
async def cancel(job_id: UUID,ctx=Depends(user)):
    await ctx[0].rpc('cancel_job',p_job=str(job_id));return {'ok':True}

@app.get('/audits')
async def audits(ctx=Depends(user)):
    return await ctx[0].rows('audits',select='id,created_at,parser_version',order='created_at.desc',limit='100')
@app.delete('/audits/{audit_id}')
async def delete_audit(audit_id: UUID,ctx=Depends(user)):
    # delete_item is owner-scoped and keeps the opaque manifest for cleanup;
    # students never gain PDF download access, and no extra read is needed.
    await ctx[0].rpc('delete_item',p_kind='audit',p_id=str(audit_id));return {'ok':True}

@app.get('/plans')
async def plans(ctx=Depends(user)):
    return await ctx[0].rows('plans',select='id,audit_id,name,revision,created_at,updated_at,preferences,summary',order='updated_at.desc',limit='100')
@app.get('/plans/{plan_id}')
async def plan(plan_id: UUID,ctx=Depends(user)): return await ctx[0].one('plans',plan_id)
@app.post('/plans')
async def create_plan(payload: CreatePlan,ctx=Depends(user)):
    g=ctx[0];a=await g.one('audits',payload.audit_id)
    preferences=payload.preferences.model_dump()
    result=AnalysisResponse.model_validate(build_result(a['data'],payload.preferences)).model_dump()
    return await g.rpc('create_plan',p_audit=str(payload.audit_id),p_name=payload.name,p_preferences=preferences,p_result=result,p_summary=summarize(result,preferences))
@app.put('/plans/{plan_id}')
async def save_plan(plan_id: UUID,payload: SavePlan,ctx=Depends(user)):
    g=ctx[0];p=await g.one('plans',plan_id)
    if p['revision']!=payload.revision: raise HTTPException(409,'This plan changed in another tab. Reload before saving.')
    a=await g.one('audits',p['audit_id'])
    result=AnalysisResponse.model_validate(build_result(a['data'],Preferences.model_validate(p['preferences']),payload.state.model_dump())).model_dump()
    if any(s['total_credits']>s['credit_limit']+.01 for s in result['plan']['semesters'] if not s['is_unplaced']):
        raise HTTPException(422,'A term exceeds its credit ceiling. Adjust the plan before saving.')
    return await g.rpc('save_plan',p_plan=str(plan_id),p_revision=payload.revision,p_state=payload.state.model_dump(),p_result=result,p_name=payload.name,p_summary=summarize(result,p['preferences']))
@app.delete('/plans/{plan_id}')
async def delete_plan(plan_id: UUID,ctx=Depends(user)):
    await ctx[0].rpc('delete_item',p_kind='plan',p_id=str(plan_id));return {'ok':True}

@app.get('/account/export')
async def export(table: Literal['profile','audits','plans','plan_revisions','analysis_jobs']='profile', offset: int=Query(default=0,ge=0), ctx=Depends(user)):
    # One bounded record per request stays below Vercel's response-body limit.
    g,account,profile=ctx
    if table=='profile': return {'schema_version':1,'profile':profile,'email':account['email']}
    fields={'audits':'*','plans':'*','plan_revisions':'*','analysis_jobs':'id,status,created_at,error,plan_id,preferences'}
    records=await g.rows(table,select=fields[table],limit='1',offset=str(offset),order='created_at')
    return {'table':table,'records':records,'next_offset':offset+1 if records else None}
@app.delete('/account')
async def delete_my_account(ctx=Depends(user)):
    g,account,_=ctx;await g.rpc('begin_account_deletion')
    from backend.cloud.worker import delete_account
    await delete_account(account['id']);return {'ok':True}

@app.post('/maintenance')
async def maintenance(request: Request):
    secret=os.environ.get('CRON_SECRET','')
    if len(secret)<32 or not hmac.compare_digest(request.headers.get('x-cron-secret',''),secret): raise HTTPException(403,'Forbidden.')
    from backend.cloud.worker import maintenance as sweep
    return await sweep()
