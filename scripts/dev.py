#!/usr/bin/env python3
"""Run development services with .env loaded, no cloud provisioning or DB migration."""
import os,signal,subprocess,sys,time
from pathlib import Path
from dotenv import load_dotenv
root=Path(__file__).resolve().parents[1];load_dotenv(root/'.env')
env=dict(os.environ,NODE_ENV='development');children=[]
try:
    children.append(subprocess.Popen([sys.executable,'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000'],cwd=root,env=env,start_new_session=True))
    children.append(subprocess.Popen(['npm','run','dev','--','--hostname','127.0.0.1'],cwd=root/'frontend',env=env,start_new_session=True))
    while all(p.poll() is None for p in children):time.sleep(.5)
except KeyboardInterrupt:pass
finally:
    for p in children:
        if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
    for p in children:
        try:p.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
