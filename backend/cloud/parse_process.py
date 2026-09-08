"""Credential-free child process for untrusted PDF extraction. Parent enforces wall time."""
import json
import sys
import resource
from pathlib import Path

if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_CPU,(35,35))
    # RLIMIT_AS is unreliable on macOS; Linux workers enforce 1.5 GiB address space.
    if sys.platform=='linux': resource.setrlimit(resource.RLIMIT_AS,(1536*1024*1024,1536*1024*1024))
    try:
        from backend.cloud.engine import parse_documents
    except BaseException as failure:
        # Nothing has been read yet, so this message describes only our own
        # deployment and is safe to hand back for the logs.
        print(f'import: {type(failure).__name__}: {failure}'[:500],file=sys.stderr)
        print(json.dumps({'error':'The analysis service is temporarily unavailable. Please try again shortly.'}))
        sys.exit(3)
    try:
        parsed=parse_documents([Path(p).read_bytes() for p in sys.argv[1:]])
        payload=json.dumps(parsed)
        if len(payload.encode())>2500000: raise ValueError('The audit output is too large. Use fewer reports.')
        print(payload)
    except BaseException as failure:
        # Only the failure's type crosses back; a message here could quote the report.
        print(f'parse: {type(failure).__name__}',file=sys.stderr)
        print(json.dumps({'error':'This PDF could not be safely parsed. Export a text-based Full Requirements DARS report and try again.'}))
        sys.exit(2)
