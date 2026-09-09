#!/usr/bin/env python3
"""Allowlisted, clean-history release. Never copies .git, PDFs, SQLite or credentials."""
import argparse,hashlib,json,re,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RETIRED={'backend/legacy_app.py','backend/auth.py','backend/store.py','backend/audit_library.py','conftest.py','docs/LOCAL_BASELINE.md'}
ROOT_FILES={'.gitignore','.vercelignore','.env.example','.python-version','pyproject.toml','vercel.json','requirements.txt','README.md','Makefile','setup.sh','start.sh','dm'}
# .sql carries the Supabase migration and the database isolation tests; .js carries
# frontend/next.config.js, which sets every response security header. A snapshot
# missing either one deploys, but without a schema or without those headers.
SUFFIXES={'.py','.ts','.tsx','.mts','.js','.mjs','.cjs','.json','.css','.html','.md','.sql','.yml','.yaml','.toml','.txt','.lock','.sh'}
REQUIRED={'supabase/migrations/202608280001_platform.sql','frontend/next.config.js','vercel.json','.env.example'}
SECRET_PATTERNS=[rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'\b(?:ghp_|github_pat_|sb_secret_|sk_live_)[A-Za-z0-9_\-]{20,}',rb'\bAKIA[A-Z0-9]{16}\b',rb'\beyJ[A-Za-z0-9_-]{25,}\.eyJ[A-Za-z0-9_-]{25,}\.[A-Za-z0-9_-]{20,}']
def git(*args,cwd=ROOT):return subprocess.check_output(['git',*args],cwd=cwd)
def allowed(path):
    p=Path(path)
    if path in RETIRED or path.startswith('backend/tests/'):return False
    if p.name in ('AGENTS.md','CLAUDE.md'):return False
    if path in ROOT_FILES:return True
    return p.parts[0] in ('backend','frontend','scripts','tests','supabase','docs','.github') and p.suffix in SUFFIXES

def scan(path,data):
    p=Path(path)
    if p.suffix.lower() in ('.pdf','.db','.sqlite','.sqlite3') or data.startswith((b'%PDF',b'SQLite format 3')):raise ValueError('Private document/database found; publication stopped.')
    if p.name.startswith('.env') and p.name!='.env.example':raise ValueError('Environment file found; publication stopped.')
    if any(re.search(pattern,data) for pattern in SECRET_PATTERNS):raise ValueError('Potential credential found; publication stopped. Inspect locally.')
    if len(data)>4000000:raise ValueError('Unexpected large source artifact; inspect locally.')

def check_history(root):
    count=0
    for line in git('rev-list','--objects','--all',cwd=root).decode().splitlines():
        oid,_,path=line.partition(' ')
        if not path:continue
        if git('cat-file','-t',oid,cwd=root).strip()!=b'blob':continue
        scan(path,git('cat-file','blob',oid,cwd=root));count+=1
    return count

def main():
    p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');p.add_argument('--initialize',action='store_true');p.add_argument('--destination',type=Path,default=ROOT/'private-release'/'multi-major');p.add_argument('--history',action='store_true');args=p.parse_args()
    files=[s for s in git('ls-files','-z').decode().split('\0') if s and allowed(s) and (ROOT/s).is_file()]
    for f in files:
        if (ROOT/f).is_symlink():raise ValueError('Symlinks cannot enter the release.')
        scan(f,(ROOT/f).read_bytes())
    # A snapshot missing any of these still builds, so nothing else would catch it.
    missing=sorted(REQUIRED-set(files))
    if missing:raise ValueError(f'Release would omit deployment-critical files: {", ".join(missing)}')
    if args.history:print(f'History checked: {check_history(ROOT)} blobs')
    if args.check:print(f'PASS: {len(files)} allowlisted source files scanned. This is not a full DLP/security audit.');return
    if git('status','--porcelain').strip():raise ValueError('Commit reviewed source changes before making a release snapshot.')
    destination=args.destination.resolve()
    if not destination.is_relative_to(ROOT/'private-release'):raise ValueError('Destination must be under the ignored private-release directory.')
    if destination.exists():raise ValueError('Destination exists. Choose a new empty snapshot path; existing releases are never overwritten.')
    destination.mkdir(parents=True);manifest={}
    for f in files:
        target=destination/f;target.parent.mkdir(exist_ok=True,parents=True);shutil.copy2(ROOT/f,target);manifest[f]=hashlib.sha256(target.read_bytes()).hexdigest()
    (destination/'RELEASE_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    if args.initialize:
        subprocess.run(['git','init','-b','codex/vercel-platform'],cwd=destination,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','config','user.name','Multi-Major'],cwd=destination,check=True)
        subprocess.run(['git','config','user.email','maintainers@example.invalid'],cwd=destination,check=True)
        subprocess.run(['git','add','--',*files,'RELEASE_MANIFEST.json'],cwd=destination,check=True)
        subprocess.run(['git','commit','-m','Initial sanitized Multi-Major student pilot'],cwd=destination,check=True,stdout=subprocess.DEVNULL)
        assert git('rev-list','--count','HEAD',cwd=destination).strip()==b'1'
        print(f'Clean history scanned: {check_history(destination)} blobs; no remote configured.')
    print(f'Snapshot created: {destination}\nFiles: {len(files)}. No cloud deployment or paid provisioning performed.')
if __name__=='__main__':main()
