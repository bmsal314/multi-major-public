"""Deterministic hosted engine: explicit preferences, conservative unknowns, no persistence."""
from __future__ import annotations
import copy
import hashlib
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any
from backend.cloud.contracts import Preferences
from backend.pdf_parser import extract_text_bytes, parse_dars_text
from backend.premed import evaluate_premed, remaining_premed_units
from backend.course_rules import COURSE_PREREQUISITES, COURSE_COREQUISITES, ADVISOR_TRACKS
from backend.analysis import _apply_equivalences, _relevant_advisories
from backend.semester_planner import generate_plan, build_recommendations, sort_planning_units
from backend.overlap_engine import compute_overlaps
from backend.graduation_check import evaluate_graduation_readiness
from backend.cloud.decisions import apply_saved_decisions
from backend.planning_units import build_units, KNOWN_CREDITS
from backend.asu_catalog import DesignationVocabulary

PARSER_VERSION='3.0.0'


def current_term() -> str:
    now=datetime.now(ZoneInfo('America/Phoenix'))
    return f"{('Spring' if now.month<=5 else 'Summer' if now.month<=7 else 'Fall')} {now.year}"

def term_key(term):
    season,year=term.split(); return int(year)*3+['Spring','Summer','Fall'].index(season)

def advance(term, count, summer=False):
    n=term_key(term)
    while count:
        n+=1
        if summer or n%3!=1: count-=1
    return f"{['Spring','Summer','Fall'][n%3]} {n//3}"


def parse_documents(documents: list[bytes]) -> list[dict]:
    if not 1<=len(documents)<=8: raise ValueError('Choose between one and eight reports.')
    if sum(map(len,documents))>100*1024*1024: raise ValueError('Batch exceeds 100 MB.')
    parsed=[]; student_ids=set()
    for i,data in enumerate(documents):
        text=extract_text_bytes(data)
        if len(text)>1500000: raise ValueError('Report contains too much text.')
        student_ids.update(re.findall(r'(?:Student\s*(?:ID|Number)|ASU\s*ID|EMPLID)\s*[:#]?\s*(\d{9,12})',text,re.I))
        if len(student_ids)>1: raise ValueError('Reports appear to belong to different students. Upload only your own reports.')
        audit=parse_dars_text(text, f'Audit {i+1}')
        if re.search(r'\b(?:Graduate|Master|Doctoral|PhD|MBA)\b',audit['name'],re.I): raise ValueError('This pilot supports undergraduate audits only.')
        if len(audit['requirements'])>1000 or any(r['credits_remaining']>1000 for r in audit['requirements']): raise ValueError('Audit exceeds planning limits.')
        # Parser strips personal header lines before constructing retained evidence.
        audit['source_file']=f"{audit['name']} audit"
        parsed.append(audit)
    if not parsed: raise ValueError('Upload at least one DARS report.')
    chosen={}
    for audit in parsed:
        identity=(audit.get('program_code') or audit['name'],audit['summary'].get('catalog_year'),audit.get('campus',''))
        old=chosen.get(identity)
        if old is None or (audit.get('prepared_on',''),len(audit['requirements']))>(old.get('prepared_on',''),len(old['requirements'])):
            chosen[identity]=audit
    return list(chosen.values())


def _units(audits, held, prerequisites, corequisites):
    """Adapter onto :func:`backend.planning_units.build_units`.

    The previous body decided schedulability from the public ``kind`` field and
    skipped credit-bearing milestones, which silently removed every directed
    upper-division elective from the map. See ``tests/bugs/BUGS.md`` B-01.
    """
    vocabulary = DesignationVocabulary()
    for audit in audits:
        for entry in audit.get("designations", []):
            vocabulary.define(
                entry["code"], entry.get("name") or entry["code"],
                self_defined=bool(entry.get("self_defined")),
            )
    return build_units(audits, held, prerequisites, corequisites, vocabulary)


def build_result(parsed: list[dict], preferences: Preferences, state: dict | None=None) -> dict:
    started=time.perf_counter(); audits=copy.deepcopy(parsed)
    courses={}
    for a in audits:
        for c in a.pop('courses',[]):
            courses[(c['term'],c['code'],c['grade'])]=c
    completed=[c for c in courses.values() if c['status']=='complete']
    active=[c for c in courses.values() if c['status']=='in_progress']
    held={c['code'] for c in [*completed,*active]}
    rules=preferences.personal_rules
    # Major-map knowledge is scoped to the catalog it was recorded for. General science is pre-med only.
    relevant={a['name'] for a in audits if a['summary'].get('catalog_year') in ('24-25','2024-2025','Fall 2024')}
    prereqs={}; coreqs={}
    if preferences.premed:
        prereqs={k:v for k,v in COURSE_PREREQUISITES.items() if k.startswith(('BIO ','CHM ','PHY '))}
        coreqs=dict(COURSE_COREQUISITES)
    if 'Finance' in relevant:
        prereqs.update({k:v for k,v in COURSE_PREREQUISITES.items() if k.startswith(('WPC ','FIN ')) and k!='FIN 461'})
    if 'Neuroscience' in relevant:
        prereqs.update({k:v for k,v in COURSE_PREREQUISITES.items() if k in ('BIO 477','NEU 477')})
    if rules.finance_sequence: prereqs['FIN 461']=['FIN 421']
    # Alternative prerequisites must not be treated as a requirement to take both honors and non-honors courses.
    for code,group in list(prereqs.items()):
        if code=='FIN 361': prereqs[code]=[next((c for c in ('FIN 303','FIN 302') if c in held),'FIN 302')]
        if code=='WPC 348': prereqs[code]=[next((c for c in ('WPC 248','WPC 347') if c in held),'WPC 248')]
        if code=='WPC 480':
            intl=('AGB 302','ECN 306','MGT 302','MKT 425','SCM 463')
            required_codes={c for a in audits for r in a['requirements'] for c in r['course_options']}
            chosen=next((c for c in intl if c in held),next((c for c in intl if c in required_codes),''))
            prereqs[code]=[c for c in group if c not in intl]+([chosen] if chosen else [])
    replacements=[]; notes=[]
    if rules.finance_equivalence:
        replacements,notes=_apply_equivalences(audits,held)
    units,unit_notes=_units(audits,held,prereqs,coreqs); units.extend(replacements); notes.extend(unit_notes)
    premed=evaluate_premed(list(courses.values())) if preferences.premed else {'framework':'Not selected','requirements':[],'sources':[],'complete_count':0,'in_progress_count':0,'remaining_count':0}
    if preferences.premed:
        existing={u['code'] for u in units}
        for u in remaining_premed_units(premed):
            if u['code'] not in existing:
                u['prerequisites']=prereqs.get(u['code'],[]);u['corequisites']=coreqs.get(u['code'],[]);units.append(u)
    units=sort_planning_units(units)
    start=preferences.start_term or current_term()
    active_terms=[]
    for c in active:
        m=re.fullmatch(r'(FA|SP|SU)(\d{2})',c['term'])
        if m: active_terms.append(f"{dict(FA='Fall',SP='Spring',SU='Summer')[m[1]]} 20{m[2]}")
    if not preferences.start_term and active_terms:
        start=max([start,*active_terms],key=term_key)
    # The graduation term is the student's decision, not a guess.
    #
    # This used to default to twenty-four terms out and then infer a graduation
    # date from wherever the last course happened to land — which is how a
    # standing dance class produced "Path to Spring 2038". Predicting the date
    # was the wrong shape for the problem: only the student knows when they
    # intend to finish, and everything else (how heavy each term has to be,
    # whether their ceiling can get them there) follows from that.
    #
    # The fallback is a plain four-year span, stated rather than derived, for
    # API callers that omit it. The interface asks.
    end=preferences.graduation_term or advance(start,7,preferences.include_summer)
    if term_key(end)<term_key(start) or term_key(end)-term_key(start)>36: raise ValueError('The graduation term must follow the start within twelve years.')
    # The standing commitment is a legacy `personal_rules.dance` flag or the
    # general form; either way it is not a graduation requirement.
    commitment=preferences.recurring_commitment
    recurring=({'label':commitment.label,'code':commitment.code,'credits':commitment.credits,
                'include_summer':commitment.include_summer} if commitment.enabled
               else {'label':'Dance class','code':'DCE','credits':2.,'include_summer':False} if rules.dance
               else None)
    def build(window_end, with_commitment):
        return generate_plan(units,start,window_end,preferences.credits_per_term,preferences.include_summer,
            preferences.term_credit_limits,active,{c['code'] for c in completed},preferences.mcat_terms,preferences.min_credits,
            advisor_tracks=ADVISOR_TRACKS if rules.finance_sequence else [],
            course_prerequisites=prereqs,course_corequisites=coreqs,
            course_ceiling=preferences.course_ceiling or None,
            mcat_credit_ceiling=preferences.mcat_credit_ceiling,
            mcat_course_ceiling=preferences.mcat_course_ceiling,
            term_course_limits=preferences.term_course_limits,
            recurring=recurring if with_commitment else None)

    def degree_end(built):
        # When the student finishes, judged by coursework alone. A standing
        # commitment occupies every term by design, so counting it here is what
        # produced "Path to Spring 2038" for a student finishing in 2029.
        regular=[s for s in built['semesters'] if not s.get('is_unplaced')]
        occupied=[i for i,s in enumerate(regular)
                  if any(c['status'] not in ('milestone','personal') for c in s['courses'])]
        return regular, max(occupied,default=0)

    # The window is fixed by the student's target, so the commitment is simply
    # reserved inside it — it can no longer extend anything.
    plan=build(end, recurring is not None)
    # Coursework that finishes before the stated target is worth saying out
    # loud — it means they could graduate earlier — but the window still runs
    # to the term they asked for.
    regular,last=degree_end(plan)
    if regular and last < len(regular)-1:
        spare=len(regular)-1-last
        plan['warnings'].append(
            f"Your coursework finishes in {regular[last]['term']}, "
            f"{spare} term{'s' if spare!=1 else ''} before {plan['graduation_term']}. "
            "You could graduate earlier, or spread the same work more lightly.")
    # IDs depend on the requirement and its local slot, never global ordering or term.
    occurrences={}
    for semester in plan['semesters']:
        for course in semester['courses']:
            if not course['movable']: continue
            key='|'.join(course['requirement_ids'])+'|'+course['code']
            ordinal=occurrences.get(key,0);occurrences[key]=ordinal+1
            course['id']='slot:'+hashlib.sha256(f'{key}|{ordinal}'.encode()).hexdigest()[:24]
    if state:
        plan=apply_saved_decisions(plan,state.get('placements',[]),state.get('placeholders',[]),state.get('term_settings',[]),state.get('custom_courses',[]),state.get('removed_course_ids',[]))
    mcat=[s['term'] for s in plan['semesters'] if s.get('is_mcat_term')]
    readiness=evaluate_graduation_readiness(audits,plan,premed,min(mcat,key=term_key) if mcat else None)
    diagnostics=[n for a in audits for n in a.get('warnings',[])]
    # DARS does not fully define prerequisites, offering schedules, or all overlap permissions.
    checks=readiness['checks'];checks.append({'id':'coverage:advisory','label':'Advisor review required','status':'note','detail':'This is a planning draft. Course availability, all prerequisite alternatives, and double-counting permissions are not fully verified.','evidence':[]})
    if any(not a['requirements'] or any(r.get('confidence',1)==0 for r in a['requirements']) for a in audits):
        checks.append({'id':'coverage:empty','label':'Uninterpreted audit','status':'gap','detail':'Some required conditions could not be interpreted. A semester map cannot establish their completion.','evidence':[]})
        readiness['gap_count']+=1
    if diagnostics: checks.append({'id':'coverage:parser','label':'Audit interpretation needs review','status':'note','detail':'Review every parser warning before relying on this map.','evidence':diagnostics})
    readiness['note_count']=sum(c['status']=='note' for c in checks)
    readiness['status']='blocked' if readiness['gap_count'] else 'on_track_with_notes'
    advisories=_relevant_advisories(audits) if rules.finance_equivalence else []
    return {'audits':audits,'completed_courses':completed,'in_progress_courses':active,'overlaps':compute_overlaps(audits),'recommendations':build_recommendations(units),
        'premed':premed,'plan':plan,'readiness':readiness,'advisories':advisories,'warnings':list(dict.fromkeys([*notes,*diagnostics])),
        'processing_ms':int((time.perf_counter()-started)*1000),'scenario_id':None}
