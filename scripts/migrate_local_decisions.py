#!/usr/bin/env python3
"""Explicit, read-only legacy decision migration. Never reads passwords or sessions."""
import argparse,getpass,json,sqlite3
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID
import httpx
from backend.cloud.contracts import Preferences,SavePlan

def load_decisions(path,scenario_id):
    connection=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True);connection.row_factory=sqlite3.Row
    try:
        row=connection.execute('select id,name,start_term,graduation_term,options_json from scenario where id=?',(scenario_id,)).fetchone()
        if not row:raise ValueError('Local scenario not found.')
        result=dict(row)
        # This allowlist deliberately excludes account, session and audit_snapshot.
        for table in ('placement','placeholder_choice','term_setting','custom_course','removed_course'):
            result[table]=[dict(r) for r in connection.execute(f'select * from {table} where scenario_id=?',(scenario_id,))]
        return result
    finally:connection.close()

def map_decisions(local,plan):
    courses=[c for s in plan['result']['plan']['semesters'] for c in s['courses']];by_code={}
    for course in courses:by_code.setdefault(course['code'],[]).append(course)
    terms={s['term'] for s in plan['result']['plan']['semesters']};placements=[];unmatched=0;ids={}
    for old in local['placement']:
        choices=[c for c in by_code.get(old['course_code'],[]) if c['movable']]
        if len(choices)!=1 or old['term'] not in terms:unmatched+=1;continue
        new_id=choices[0]['id'];ids[old['course_id']]=new_id
        placements.append({k:old[k] for k in ('course_code','term','credits','locked')}|{'course_id':new_id})
    # Old opaque placeholder IDs cannot establish the new requirement's identity.
    # Report them, never guess which degree a choice should satisfy.
    unmatched+=len(local['placeholder_choice'])
    custom=[]
    for c in local['custom_course']:
        if c['term'] not in terms:unmatched+=1;continue
        custom.append({k:c[k] for k in ('course_id','code','label','credits','term','note')}|{'majors':json.loads(c['majors_json'])})
    removed=[ids[r['course_id']] for r in local['removed_course'] if r['course_id'] in ids]
    unmatched+=sum(r['course_id'] not in ids for r in local['removed_course'])
    settings=[{k:r[k] for k in ('term','credit_limit','is_mcat_term','note')} for r in local['term_setting'] if r['term'] in terms]
    state=SavePlan(revision=plan['revision'],state={'placements':placements,'placeholders':[],'term_settings':settings,'custom_courses':custom,'removed_course_ids':removed}).state.model_dump()
    return state,unmatched

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',type=Path,required=True);p.add_argument('--scenario-id',type=int,required=True);p.add_argument('--origin',required=True);p.add_argument('--expected-user',type=UUID,required=True);p.add_argument('--plan-id',type=UUID,required=True);p.add_argument('--personal-defaults',action='store_true',help='Opt into this local owner’s Finance, dance and pre-med defaults');p.add_argument('--apply',action='store_true',help='Create a new cloud plan and migrate compatible decisions; otherwise only report counts');args=p.parse_args()
    origin=args.origin.rstrip('/');url=urlparse(origin)
    if url.scheme!='https' or url.path not in ('','/'):p.error('Use the HTTPS origin of your trusted deployed Multi-Major site.')
    local=load_decisions(args.database,args.scenario_id)
    with httpx.Client(base_url=origin,timeout=60,follow_redirects=False) as client:
        response=client.get('/api/auth/session');response.raise_for_status();csrf=response.json()['csrf']
        headers={'Origin':origin,'X-CSRF-Token':csrf}
        response=client.post('/api/auth/login',headers=headers,json={'email':input('Verified account email: ').strip(),'password':getpass.getpass('Account password: ')});response.raise_for_status()
        try:
            session=client.get('/api/auth/session').json()
            if session.get('user',{}).get('id')!=str(args.expected_user):raise ValueError('Verified account ID does not match --expected-user. Nothing migrated.')
            r=client.get('/api/v1/plans/'+str(args.plan_id));r.raise_for_status();plan=r.json()
            prefs=plan['preferences']
            if args.personal_defaults:
                prefs=Preferences(**(prefs|{'premed':True,'start_term':local['start_term'],'graduation_term':local['graduation_term'],'min_credits':13,'credits_per_term':max(13,prefs['credits_per_term']),'personal_rules':{'finance_equivalence':True,'finance_sequence':True,'dance':True}})).model_dump()
            state,unmatched=map_decisions(local,plan)
            print(json.dumps({'mode':'apply' if args.apply else 'dry-run','compatible_moves':len(state['placements']),'custom_courses':len(state['custom_courses']),'unmatched_decisions':unmatched,'personal_defaults':args.personal_defaults}))
            if not args.apply:return
            r=client.post('/api/v1/plans',headers=headers,json={'audit_id':plan['audit_id'],'name':'Imported local decisions','preferences':prefs});r.raise_for_status();plan=r.json()
            state,unmatched=map_decisions(local,plan)
            r=client.put('/api/v1/plans/'+plan['id'],headers=headers,json={'revision':plan['revision'],'state':state});r.raise_for_status()
            if args.personal_defaults:client.put('/api/v1/profile',headers=headers,json={'preferences':prefs}).raise_for_status()
            print('New cloud map saved. Review unmatched placeholder choices manually. Original local and cloud maps are unchanged.')
        finally:client.post('/api/auth/logout',headers=headers,json={})
if __name__=='__main__':main()
