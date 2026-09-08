#!/usr/bin/env python3
"""UI-only tests with synthetic API fixtures. Does NOT validate Supabase authentication."""
import json,os,subprocess,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
base=os.environ.get('UI_BASE_URL','http://127.0.0.1:3000')
fixture=json.loads(subprocess.check_output([sys.executable,'-m','tests.cloud.fixture_result'],cwd=ROOT,text=True))
report=Path(os.environ.get('UI_REPORT_DIR','/tmp/multi-major-ui'));report.mkdir(exist_ok=True,parents=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    violations=[]
    page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    # First inspect the real fail-closed page before applying UI fixtures.
    page.goto(base);page.get_by_role('heading',name='More than one path. One clear plan.').wait_for()
    page.screenshot(path=str(report/'welcome.png'),full_page=True)
    assert not page.get_by_role('button',name='Create account',exact=True).last.is_enabled()
    # The sign-in form can only submit once it holds a CSRF token, and the token
    # arrives with the session lookup. That lookup must answer "signed out"
    # rather than erroring when account services are unreachable, or an outage
    # would disable the one screen that could recover from it.
    unconfigured=page.request.get(base+'/api/auth/session')
    assert unconfigured.status==200,f'session lookup failed closed: {unconfigured.status}'
    assert unconfigured.json()['csrf'] and unconfigured.json()['user'] is None
    signed_in=False;save_requests=[]
    def api(route):
        nonlocal_unused=None
        path=route.request.url.split('/api/',1)[1]
        if path=='auth/session':data={'csrf':'synthetic-ui-token','email_ready':True,'user':{'id':'11111111-1111-4111-8111-111111111111','email':'student@example.invalid'} if signed_in else None}
        elif path=='v1/plans':data=[{k:v for k,v in fixture.items() if k not in ('result','state')}]
        elif path.startswith('v1/plans/'):
            if route.request.method=='PUT':
                body=route.request.post_data_json;save_requests.append(body);fixture['revision']+=1;fixture['state']=body['state']
            data=fixture
        elif path=='v1/analyses':data=[]
        elif path=='v1/profile':data={'preferences':fixture['preferences']}
        elif path=='v1/audits':data=[{'id':fixture['audit_id'],'created_at':'2026-08-28T12:00:00Z'}]
        else:data={}
        route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
    page.route('**/api/**',api)
    def check(label):
        # Browser-side axe injection is test-only; CSP stays enabled in the app.
        page.evaluate((ROOT/'frontend/node_modules/axe-core/axe.min.js').read_text())
        results=page.evaluate("async () => (await axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations")
        (report/f'{label}-axe.json').write_text(json.dumps(results,indent=2))
        if results: print(label,[(r['id'],len(r['nodes'])) for r in results])
        violations.extend((label,r['id'],[n['html'] for n in r['nodes']]) for r in results)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),f'{label}: horizontal page overflow'
    page.reload();page.get_by_role('heading',name='A home for your next semester.').wait_for();check('welcome')
    page.keyboard.press('Tab');assert page.locator('.skip-link').evaluate('(e)=>e===document.activeElement')
    signed_in=True;page.reload();page.get_by_role('heading',name='Plan what comes next.').wait_for();page.screenshot(path=str(report/'workspace.png'),full_page=True);check('workspace')
    page.get_by_role('button',name='Open map →').click();page.get_by_text('Revision 1',exact=True).wait_for();page.screenshot(path=str(report/'map.png'),full_page=True);check('map')
    # Find native movement selects; keyboard changes must participate in save state.
    moves=page.get_by_role('combobox',name='Move CSE 110 to',exact=True)
    assert moves.count()>0,'No keyboard movement control found'
    if moves.count():
        select=moves.first;options=select.locator('option').all_text_contents()
        if len(options)>1:
            select.focus();before=select.input_value();page.keyboard.press('ArrowDown');page.keyboard.press('Tab');page.wait_for_timeout(2000);print('Keyboard movement:',before,'->',select.input_value(),'saves:',len(save_requests))
            assert save_requests,'Keyboard movement did not autosave'
            assert save_requests[-1]['revision']>=1
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(report/'map-mobile.png'),full_page=True);check('map-mobile')
    page.goto(base+'/account');page.get_by_role('heading',name='Your account').wait_for();check('account')
    page.goto(base+'/privacy');page.get_by_role('heading').first.wait_for();check('privacy')
    assert not errors,errors
    assert not violations,violations
    browser.close();print(f'PASS: UI fixture, axe and keyboard checks. Screenshots: {report}')
