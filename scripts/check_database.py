#!/usr/bin/env python3
"""Run SQL isolation tests on a disposable PostgreSQL cluster, never an existing DB."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
binpath=os.environ.get('POSTGRES_BIN','/opt/homebrew/opt/postgresql@18/bin')
if not (Path(binpath)/'initdb').exists():
    found=shutil.which('initdb')
    if not found: raise SystemExit('Set POSTGRES_BIN to an existing PostgreSQL bin directory.')
    binpath=str(Path(found).parent)
# initdb runs with --no-locale, and PostgreSQL 18 on macOS refuses to start when
# the inherited locale makes the postmaster multithreaded during startup. Pin the
# cluster's locale to match the one it was created with.
ENV=dict(os.environ,LC_ALL='C',LANG='C')
def run(tool,*args,**kw):
    return subprocess.run([str(Path(binpath)/tool),*args],check=True,text=True,capture_output=True,env=ENV,**kw)
with tempfile.TemporaryDirectory(prefix='mm-db-') as directory:
    data=Path(directory)/'data';sock=Path(directory)/'socket';sock.mkdir()
    run('initdb','-D',str(data),'-A','trust','--no-locale')
    run('pg_ctl','-D',str(data),'-l',str(Path(directory)/'server.log'),'-o',f"-k {sock} -h '' -p 55439",'-w','start')
    try:
        args=['-h',str(sock),'-p','55439','-d','postgres','-v','ON_ERROR_STOP=1']
        run('psql',*args,input=(ROOT/'tests/cloud/database_bootstrap.sql').read_text())
        run('psql',*args,input=(ROOT/'supabase/migrations/202608280001_platform.sql').read_text())
        r=run('psql',*args,input=(ROOT/'tests/cloud/database_assertions.sql').read_text())
        print(r.stdout)
        print('PASS: disposable PostgreSQL migration and isolation assertions')
    except subprocess.CalledProcessError as error:
        print(error.stdout);print(error.stderr);raise SystemExit(1)
    finally: run('pg_ctl','-D',str(data),'-m','fast','-w','stop')
