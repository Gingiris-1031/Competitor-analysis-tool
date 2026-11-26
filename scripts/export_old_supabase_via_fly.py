"""GET-only old Supabase export through the existing Fly app credentials.

Credentials remain in the container. Captured data goes directly to local 0600
files, not console output. Auth Admin export does NOT contain password hashes.
"""
import argparse
import os
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from datetime import datetime, timezone
from export_insforge_for_migration import atomic_json

REMOTE = r'''
import os,json,sys,urllib.request,urllib.parse
base=os.environ['SUPABASE_URL'].rstrip('/')
assert base == 'https://nkunysycqapregxubcil.supabase.co', 'Unexpected source'
key=os.environ['SUPABASE_SERVICE_KEY']
headers={'apikey':key,'Authorization':'Bearer '+key,'Prefer':'count=exact'}
def get(path):
    req=urllib.request.Request(base+path,headers=headers)
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.load(r),r.headers
mode=MODE
if mode == 'openapi':
    data,_=get('/rest/v1/')
elif mode == 'auth_users':
    data=[]; seen=set(); page=1
    while True:
        payload,_=get('/auth/v1/admin/users?per_page=100&page='+str(page))
        batch=payload['users']
        if not batch: break
        for row in batch:
            assert row['id'] not in seen, 'Repeated auth user'
            seen.add(row['id'])
        data.extend(batch); page+=1
else:
    table=mode
    schema,_=get('/rest/v1/')
    props=schema.get('definitions',{}).get(table,{}).get('properties',{})
    keys=[name for name,meta in props.items() if '<pk/>' in meta.get('description','')]
    assert keys, 'No verified primary key in OpenAPI'
    def count():
        _,h=get('/rest/v1/'+table+'?select='+urllib.parse.quote(','.join(keys))+'&limit=1')
        total=h.get('Content-Range','').rsplit('/',1)[-1]
        assert total.isdigit(), 'Missing exact count'
        return int(total)
    expected=count(); seen=set(); offset=0
    while True:
        q=urllib.parse.urlencode({'select':'*','order':','.join(k+'.asc' for k in keys),'limit':25,'offset':offset})
        batch,_=get('/rest/v1/'+table+'?'+q)
        assert isinstance(batch,list), 'Expected rows'
        if not batch: break
        for row in batch:
            identity=tuple(row[k] for k in keys)
            assert identity not in seen, 'Duplicate key during export'
            seen.add(identity)
        print(json.dumps({'migration_kind':'page','rows':batch},ensure_ascii=False),flush=True)
        offset+=len(batch)
    assert len(seen)==expected==count(), 'Source changed or incomplete export'
    print(json.dumps({'migration_kind':'end','count':len(seen),'expected':expected}),flush=True)
    sys.exit(0)
print(json.dumps(data,ensure_ascii=False))
'''


def fetch(mode):
    code = REMOTE.replace('mode=MODE', 'mode=' + repr(mode))
    result = subprocess.run(['flyctl', 'ssh', 'console', '--app', 'competitor-analysis-tool',
                             '--machine', os.environ.get('MIGRATION_FLY_MACHINE', 'd891e035c95738'),
                             '--quiet', '-C', 'python -c ' + shlex.quote(code)],
                            capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError('Remote read failed; response body suppressed')
    if mode in {'openapi','auth_users'}:
        return json.loads(result.stdout)
    rows=[]
    frames=[json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if not frames or frames[-1].get('migration_kind')!='end':
        raise ValueError('Missing export completion marker')
    for frame in frames[:-1]:
        if frame.get('migration_kind')!='page':
            raise ValueError('Unexpected export frame')
        rows.extend(frame['rows'])
    if len(rows)!=frames[-1]['count'] or len(rows)!=frames[-1]['expected']:
        raise ValueError('Truncated export stream')
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,mode=0o700,exist_ok=False)
    manifest={'source':'nkunysycqapregxubcil','status':'incomplete',
              'transaction_consistent':False,'auth_password_hashes_included':False,
              'started_at':datetime.now(timezone.utc).isoformat(),'objects':{}}
    atomic_json(args.output/'manifest.json',manifest)
    schema=fetch('openapi')
    atomic_json(args.output/'openapi.json',schema)
    # Only paths advertising GET and a matching table definition are exported.
    tables=sorted(path[1:] for path,methods in schema.get('paths',{}).items()
                  if path.count('/')==1 and path[1:] in schema.get('definitions',{}) and 'get' in methods)
    if not tables:
        raise RuntimeError('No tables discovered; refusing an empty-success export')
    failed=False
    for name in tables+['auth_users']:
        try:
            rows=fetch(name)
            if not isinstance(rows,list): raise ValueError('Expected row array')
            path=args.output/(name+'.json')
            atomic_json(path,rows)
            manifest['objects'][name]={'status':'exported','rows':len(rows),
                                       'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            print(f'{name}: exported {len(rows)} rows',flush=True)
        except Exception as exc:
            failed=True
            manifest['objects'][name]={'status':'failed','error_type':type(exc).__name__}
            print(f'{name}: failed ({type(exc).__name__})',flush=True)
        atomic_json(args.output/'manifest.json',manifest)
    manifest['status']='incomplete' if failed else 'rows_exported_requires_final_snapshot'
    manifest['finished_at']=datetime.now(timezone.utc).isoformat()
    atomic_json(args.output/'manifest.json',manifest)
    return 1 if failed else 0


if __name__=='__main__':
    raise SystemExit(main())
