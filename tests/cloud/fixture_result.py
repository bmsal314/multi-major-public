"""Print a synthetic UI fixture. Never reads local student files."""
import json
from backend.cloud.engine import parse_documents,build_result
from backend.cloud.contracts import Preferences
from backend.models import AnalysisResponse
from tests.cloud.fixtures import audit_text,pdf
p=Preferences(start_term='Fall 2026',graduation_term='Spring 2028')
r=AnalysisResponse.model_validate(build_result(parse_documents([pdf(audit_text())]),p)).model_dump()
print(json.dumps({'id':'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','audit_id':'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','name':'Synthetic semester map','revision':1,'updated_at':'2026-08-28T12:00:00Z','preferences':p.model_dump(),'state':{},'result':r}))
