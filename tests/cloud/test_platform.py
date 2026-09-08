from copy import deepcopy
from datetime import datetime,timezone
from uuid import uuid4
import os
import json
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from backend.cloud.contracts import Preferences,UploadRequest,SavePlan,UploadTicket
from backend.cloud.engine import build_result,parse_documents
from backend.pdf_parser import parse_dars_text,extract_text_bytes
from backend.models import AnalysisResponse
from backend.premed import evaluate_premed
from tests.cloud.fixtures import pdf,audit_text

@pytest.fixture
def parsed():return [parse_dars_text(audit_text(),'Synthetic audit')]

def test_upload_limits():
    assert UploadRequest(files=[{'size':100}],consent=True).preferences.min_credits==0
    for body in ({'files':[],'consent':True},{'files':[{'size':26*1024*1024}],'consent':True},{'files':[{'size':25*1024*1024}]*5,'consent':True},{'files':[{'size':100,'filename':'private.pdf'}],'consent':True},{'files':[{'size':100}],'consent':False}):
        with pytest.raises(ValidationError):UploadRequest.model_validate(body)

def test_upload_ticket_carries_a_real_length_signed_url():
    # Storage signs uploads with a JWT in the query string, so a real ticket URL
    # runs to roughly 650 characters. The model's global 500-char guard used to
    # apply here too, so serialising the response raised ResponseValidationError
    # and no upload could ever begin. Guard the length that actually occurs.
    url='https://project.supabase.co/storage/v1/object/upload/sign/audit-uploads/'+str(uuid4())+'/'+str(uuid4())+'/1.pdf?token='+'t'*470
    assert len(url)>500
    ticket=UploadTicket(job_id=uuid4(),uploads=[{'url':url,'path':'a/b/1.pdf'}])
    assert ticket.model_dump()['uploads'][0]['url']==url
    # Still bounded, and the guard still applies to ordinary models.
    with pytest.raises(ValidationError):UploadTicket(job_id=uuid4(),uploads=[{'url':'x'*2500,'path':'p'}])
    with pytest.raises(ValidationError):Preferences(start_term='x'*600)

@pytest.mark.parametrize('kwargs',[{'min_credits':20},{'credits_per_term':31},{'start_term':'yesterday'},{'start_term':'Fall 2027','graduation_term':'Spring 2026'},{'mcat_terms':['Fall 2026']},{'term_credit_limits':{'Fall 2026':99}}])
def test_preferences_invalid(kwargs):
    with pytest.raises(ValidationError):Preferences(**kwargs)

def test_body_is_real_pdf():
    data=pdf(audit_text());assert b'%PDF' in data;assert 'CSE 110' in extract_text_bytes(data)
    assert parse_documents([data])[0]['name']=='Computer Science'

@pytest.mark.parametrize('data',[b'not a pdf',pdf(''),pdf(audit_text(),81),b'%PDF-'+b'x'*(25*1024*1024)])
def test_unsafe_documents_rejected(data):
    with pytest.raises(Exception):parse_documents([data])

@pytest.mark.parametrize('program,code',[('Mechanical Engineering','ESBSME'),('History','LABAHIS'),('Nursing','NUDBSN'),('Music','FABAMUS'),('Minor in Spanish','LASPANMIN'),('Certificate in Sustainability','SOSCERT'),('Barrett Honors College','HONORS'),('Finance','BAFINBS'),('Neuroscience','LANEUROBS')])
def test_program_metadata_not_filename(program,code):
    a=parse_dars_text(audit_text(program,code),'misleading-finance.pdf')
    assert a['program_code']==code
    assert a['name'].casefold()==program.casefold()
    assert len(a['requirements'])>=2

def test_newest_equivalent_audit_selected():
    first=pdf(audit_text(date='08/01/2026'));last=pdf(audit_text(date='08/25/2026'))
    result=parse_documents([last,first]);assert len(result)==1;assert result[0]['prepared_on'].startswith('2026-08-25')

def test_distinct_catalogs_preserved():
    assert len(parse_documents([pdf(audit_text(catalog='2025-2026')),pdf(audit_text())]))==2

def test_student_identity_removed():
    a=parse_documents([pdf(audit_text(extra='Student Name: Synthetic Person\nStudent ID: 1234567890\nEmail: synthetic@example.invalid'))])[0]
    rendered=json.dumps(a);assert 'Synthetic Person' not in rendered;assert '1234567890' not in rendered;assert 'synthetic@example.invalid' not in rendered

def test_mixed_students_rejected():
    with pytest.raises(ValueError,match='different students'):parse_documents([pdf(audit_text(extra='Student ID: 1234567890')),pdf(audit_text(extra='Student ID: 9876543210'))])

def test_graduate_rejected():
    with pytest.raises(ValueError,match='undergraduate'):parse_documents([pdf(audit_text(program='Master of Engineering'))])

def test_defaults_never_inherit_personal_rules(parsed):
    r=AnalysisResponse.model_validate(build_result(parsed,Preferences(start_term='Fall 2026')))
    assert not r.premed.requirements;assert r.plan.min_credits==0
    assert all(s.credit_limit==15 for s in r.plan.semesters if not s.is_unplaced)
    assert not any(c.status=='personal' for s in r.plan.semesters for c in s.courses)
    assert r.readiness.status!='on_track'

def test_four_credit_course_not_split(parsed):
    r=build_result(parsed,Preferences(start_term='Fall 2026'))
    courses=[c for s in r['plan']['semesters'] for c in s['courses'] if c['code']=='CSE 110']
    assert len(courses)==1;assert courses[0]['credits']==4

def test_empty_audit_never_on_track(parsed):
    parsed[0]['requirements']=[]
    assert build_result(parsed,Preferences(start_term='Fall 2026'))['readiness']['status']=='blocked'

def test_ids_survive_filename_and_renamed_label():
    a=parse_dars_text(audit_text(),'a.pdf');b=parse_dars_text(audit_text().replace('Technical elective','Technical selection'),'b.pdf')
    assert [r['id'] for r in a['requirements']]==[r['id'] for r in b['requirements']]

def test_plan_ids_survive_unrelated_requirement(parsed):
    p=Preferences(start_term='Fall 2026')
    first=build_result(parsed,p);new=deepcopy(parsed);extra=deepcopy(new[0]['requirements'][0]);extra.update(id='new',name='AAA 100',course_options=['AAA 100']);new[0]['requirements'].insert(0,extra)
    last=build_result(new,p)
    find=lambda r:next(c['id'] for s in r['plan']['semesters'] for c in s['courses'] if c['code']=='CSE 110')
    assert find(first)==find(last)

def test_saved_credits_survive_replay(parsed):
    p=Preferences(start_term='Fall 2026');r=build_result(parsed,p);s=r['plan']['semesters'][0];c=next(c for c in s['courses'] if c['code']=='CSE 110')
    saved=build_result(parsed,p,{'placements':[{'course_id':c['id'],'term':s['term'],'credits':5}]})
    assert next(c['credits'] for s in saved['plan']['semesters'] for c in s['courses'] if c['code']=='CSE 110')==5

def test_unmatched_edits_visible(parsed):
    r=build_result(parsed,Preferences(start_term='Fall 2026'),{'placements':[{'course_id':'old','term':'Fall 2026','credits':3}]})
    assert any('no longer matches' in w for w in r['plan']['warnings'])

def test_saved_state_bounded():
    for value in (-1,float('inf'),13):
        with pytest.raises(ValidationError):SavePlan(revision=1,state={'placements':[{'course_id':'x','term':'Fall 2026','credits':value}]})

def test_premed_labs_statistics_and_writing():
    courses=[{'code':c,'status':'complete'} for c in ['CHM 117','CHM 118','ENG 105','HON 272']]
    result=evaluate_premed(courses);rules={r['id']:r for r in result['requirements']}
    assert rules['chm-111']['remaining_courses']==['CHM 111'];assert rules['chm-112']['remaining_courses']==['CHM 112']
    assert not rules['statistics']['required'];assert rules['english']['status']=='remaining'
    courses.append({'code':'HON 171','status':'complete'})
    assert next(r for r in evaluate_premed(courses)['requirements'] if r['id']=='english')['status']=='complete'

def test_private_api_boundaries(monkeypatch):
    from backend.main import app
    monkeypatch.setenv('INTERNAL_API_SECRET','x'*32)
    with TestClient(app) as c:
        assert c.get('/health').status_code==403
        assert c.get('/plans',headers={'x-internal-secret':'x'*32}).status_code==401
        assert c.post('/uploads',headers={'x-internal-secret':'x'*32},content=b'x'*1048577).status_code==413
        assert c.get('/health',headers={'x-internal-secret':'x'*32,'content-length':'invalid'}).status_code==200
        for path in ['/docs','/audits/files','/demo','/shutdown']:
            assert c.get(path,headers={'x-internal-secret':'x'*32}).status_code in (404,405)

def test_queue_subscriber_imports():
    import backend.cloud.worker

@pytest.mark.asyncio
async def test_extraction_child_has_no_credentials(monkeypatch):
    from backend.cloud.worker import parse_isolated
    payload=pdf(audit_text())
    class G:
        async def download(self,path):return payload
    monkeypatch.setenv('SUPABASE_SECRET_KEY','test-secret-not-for-child')
    result=await parse_isolated(G(),[{'path':'synthetic','size':len(payload)}])
    assert result[0]['name']=='Computer Science'

@pytest.mark.asyncio
async def test_extraction_child_can_import_vendored_dependencies(monkeypatch):
    """Hosts vendor dependencies beside the app rather than into the interpreter.

    A child given only the project root on PYTHONPATH cannot import pdfplumber
    there, and every report is rejected as unreadable. The child's environment
    must carry this process's search path, and still none of its credentials.
    """
    import sys
    from backend.cloud import worker
    captured={}
    class Process:
        returncode=0
        async def communicate(self):return json.dumps([{'name':'Synthetic'}]).encode(),b''
    async def spawn(*args,**kwargs):captured.update(kwargs);return Process()
    monkeypatch.setattr(worker.asyncio,'create_subprocess_exec',spawn)
    monkeypatch.setenv('SUPABASE_SECRET_KEY','test-secret-not-for-child')
    class G:
        async def download(self,path):return b'%PDF-1.4 stand-in'
    await worker.parse_isolated(G(),[{'path':'synthetic','size':17}])
    path=captured['env']['PYTHONPATH'].split(os.pathsep)
    assert [entry for entry in sys.path if entry not in ('','.')]  # a real search path exists
    for entry in sys.path:
        if entry not in ('','.'):assert entry in path,f'{entry} is missing; imports would fail'
    assert 'test-secret-not-for-child' not in json.dumps(captured['env'])
    assert set(captured['env'])=={'PATH','PYTHONPATH','PYTHONIOENCODING'}

@pytest.mark.asyncio
async def test_cleanup_failure_remains_retryable(monkeypatch,parsed):
    from backend.cloud import worker
    jobid=str(uuid4());userid=str(uuid4());job={'id':jobid,'user_id':userid,'status':'processing','manifest':[],'attempts':1,'preferences':{},'created_at':datetime.now(timezone.utc).isoformat()}
    class G:
        calls=[]
        async def rpc(self,name,**kw):
            self.calls.append(name)
            if name=='worker_claim':return job
            if name=='worker_finish':job['status']='completed'
        async def rows(self,*args,**kw):return [job]
        async def remove_objects(self,paths):raise RuntimeError('storage unavailable')
    async def parse(*args):return parsed
    monkeypatch.setattr(worker,'parse_isolated',parse);g=G();await worker.process_job(jobid,g)
    assert 'worker_finish' in g.calls;assert 'worker_fail' not in g.calls

def test_release_snapshot_keeps_deployment_critical_files():
    """A snapshot without these builds and deploys, so nothing else catches it."""
    import importlib.util,pathlib
    root=pathlib.Path(__file__).resolve().parents[2]
    spec=importlib.util.spec_from_file_location('release_check',root/'scripts/prepare_release.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for path in ('supabase/migrations/202608280001_platform.sql','frontend/next.config.js',
                 'tests/cloud/database_assertions.sql','vercel.json','.env.example'):
        assert (root/path).is_file(),path
        assert module.allowed(path),f'{path} would be dropped from the published repository'

def test_placeholder_choice_must_come_from_the_listed_courses(parsed):
    """The editor offers the same list, so an unlisted code must not appear valid.

    Any slot that still offers alternatives is selectable, not only an unnamed
    placeholder: the unit builder now names a concrete course when DARS lists a
    small enough set, and the student must still be able to pick the other one.
    """
    from backend.cloud.decisions import apply_saved_decisions
    p=Preferences(start_term='Fall 2026')
    slot=next(c for s in build_result(parsed,p)['plan']['semesters'] for c in s['courses'] if c['alternatives'])
    assert slot['alternatives'],'this fixture is only meaningful for a slot with listed courses'
    listed=build_result(parsed,p,{'placeholders':[{'slot_id':slot['id'],'course_code':slot['alternatives'][0],'requirement_id':'','note':''}]})
    filled=[c for s in listed['plan']['semesters'] for c in s['courses'] if c['id']==slot['id']]
    assert filled and not filled[0]['is_placeholder']
    unlisted=build_result(parsed,p,{'placeholders':[{'slot_id':slot['id'],'course_code':'ZZZ 999','requirement_id':'','note':''}]})
    still=[c for s in unlisted['plan']['semesters'] for c in s['courses'] if c['id']==slot['id']]
    # The safety property is that the slot is left exactly as it was, which holds
    # whether it was an unnamed placeholder or a named course offering a swap.
    assert still and still[0]['code']==slot['code'] and still[0]['is_placeholder']==slot['is_placeholder']
    assert any('not a listed alternative' in w for w in unlisted['plan']['warnings'])

def test_custom_courses_with_the_same_name_both_survive(parsed):
    p=Preferences(start_term='Fall 2026');term=build_result(parsed,p)['plan']['semesters'][0]['term']
    state={'custom_courses':[
        {'course_id':f'custom:{term}:studio-time','code':'','label':'Studio time','credits':1,'term':term,'majors':[],'note':''},
        {'course_id':f'custom:{term}:studio-time-2','code':'','label':'Studio time','credits':1,'term':term,'majors':[],'note':''}]}
    result=build_result(parsed,p,state)
    added=[c for s in result['plan']['semesters'] for c in s['courses'] if c['label']=='Studio time']
    assert len(added)==2
