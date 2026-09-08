#!/usr/bin/env python3
"""Opt-in staging-only load exercise. Requires 100 pre-created verified synthetic accounts."""
import argparse,asyncio,json,os,stat,time
from pathlib import Path
import httpx
from tests.cloud.fixtures import pdf,audit_text

def percentile(values,p=.95):return sorted(values)[min(len(values)-1,int(len(values)*p))] if values else None
async def run(args):
    if not args.allow_staging_load or not args.origin.startswith('https://'):raise ValueError('Explicit --allow-staging-load and an HTTPS staging origin are required.')
    if stat.S_IMODE(args.accounts.stat().st_mode)&0o077:raise ValueError('Synthetic account credential file must be mode 0600.')
    accounts=json.loads(args.accounts.read_text())
    if len(accounts)!=100:raise ValueError('Provide exactly 100 verified synthetic accounts, each with a saved synthetic map.')
    origin=args.origin.rstrip('/');clients=[];latencies=[];durations=[];failures=[]
    async def participant(index,account):
        client=httpx.AsyncClient(base_url=origin,timeout=90);clients.append(client)
        try:
            session=await client.get('/api/auth/session');session.raise_for_status();headers={'Origin':origin,'X-CSRF-Token':session.json()['csrf']}
            login=await client.post('/api/auth/login',headers=headers,json=account);login.raise_for_status()
            listing=await client.get('/api/v1/plans');listing.raise_for_status()
            if not listing.json():raise ValueError('Missing synthetic saved plan.')
            start=time.perf_counter();result=await client.get('/api/v1/plans/'+listing.json()[0]['id']);result.raise_for_status();latencies.append(time.perf_counter()-start)
            await barrier.wait()
            if index>=20:return
            docs=[pdf(audit_text(program=n,code=c)) for n,c in [('Computer Science','CS'),('Minor in Spanish','SP'),('Certificate in Sustainability','SU')]]
            ticket=await client.post('/api/v1/uploads',headers=headers,json={'files':[{'size':len(d)} for d in docs],'preferences':{},'consent':True});ticket.raise_for_status();data=ticket.json()
            for obj,content in zip(data['uploads'],docs):
                r=await client.put(obj['url'],content=content,headers={'Content-Type':'application/pdf','x-upsert':'false'});r.raise_for_status()
            start=time.perf_counter();r=await client.post('/api/v1/analyses',headers=headers,json={'job_id':data['job_id']});r.raise_for_status()
            while time.perf_counter()-start<300:
                job=await client.get('/api/v1/analyses/'+data['job_id']);job.raise_for_status();status=job.json()['status']
                if status=='completed':durations.append(time.perf_counter()-start);return
                if status in ('failed','cancelled'):raise ValueError('Synthetic analysis failed.')
                await asyncio.sleep(1)
            raise TimeoutError('Analysis exceeded five minutes.')
        except Exception as error:
            failures.append(type(error).__name__)
            await barrier.abort()
    barrier=asyncio.Barrier(100)
    try:await asyncio.gather(*(participant(i,a) for i,a in enumerate(accounts)))
    finally:
        for client in clients:await client.aclose()
    report={'users':100,'requested_jobs':20,'successful_saved_reads':len(latencies),'successful_jobs':len(durations),'saved_read_p95_seconds':percentile(latencies),'three_audit_job_p95_seconds':percentile(durations),'failures':len(failures),'measured_provider_cost_usd':None,'note':'Record provider billing separately; no cost is inferred from local runtime.'}
    print(json.dumps(report,indent=2))
    if failures or len(durations)!=20 or percentile(latencies)>=2 or percentile(durations)>=60:raise SystemExit(1)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--origin',required=True);p.add_argument('--accounts',type=Path,required=True);p.add_argument('--allow-staging-load',action='store_true');asyncio.run(run(p.parse_args()))
