"""Import verified backups into an isolated, inaccessible rehearsal schema.

Not a production schema: only observed column types and primary keys are
enforced. No production RLS policies, defaults, triggers or Auth are installed.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

TARGET = 'miscpkgclgixmqjftscl'
SCHEMA = 'analook_migration_20261125'
TYPES = {'boolean','integer','jsonb','text','text[]','timestamp with time zone','uuid'}


def read_json(path):
    return json.loads(path.read_text())


def verify_folder(folder, section):
    manifest = read_json(folder/'manifest.json')
    if manifest['status'] != 'rows_exported_requires_final_snapshot':
        raise ValueError('Incomplete source export')
    for table, info in manifest[section].items():
        path = folder/(table+'.json')
        if info['status'] != 'exported' or hashlib.sha256(path.read_bytes()).hexdigest() != info['sha256']:
            raise ValueError('Source checksum mismatch: '+table)
        if len(read_json(path)) != info['rows']:
            raise ValueError('Source row count mismatch: '+table)
    return manifest


def build_plan(root):
    old=root/'old-supabase-rows-01'; new=root/'insforge-rows-01'
    old_manifest=verify_folder(old,'objects'); new_manifest=verify_folder(new,'tables')
    definitions=read_json(old/'openapi.json')['definitions']
    plan={}
    for table in old_manifest['objects']:
        if table=='auth_users': continue
        definition=definitions[table]
        columns={k:v['format'] for k,v in definition['properties'].items()}
        keys=[k for k,v in definition['properties'].items() if '<pk/>' in v.get('description','')]
        plan[table]={'columns':columns,'keys':keys,'path':old/(table+'.json')}
    constraints=read_json(root/'insforge-constraints.json')['rows']
    for table in new_manifest['tables']:
        entry=plan.setdefault(table,{'columns':{},'keys':[],'path':new/(table+'.json')})
        for col in read_json(root/'insforge-columns.json')['rows']:
            if col['table_name']!=table: continue
            name=col['column_name']; kind=col['data_type']
            if name in entry['columns'] and entry['columns'][name]!=kind:
                raise ValueError('Type conflict: '+table+'.'+name)
            entry['columns'][name]=kind
        for c in constraints:
            if c['table_name']==table and c['definition'].startswith('PRIMARY KEY ('):
                keys=c['definition'][13:-1].split(', ')
                if entry['keys'] and entry['keys']!=keys: raise ValueError('Primary key conflict')
                entry['keys']=keys
    # Rebuild from checksum-verified inputs; do not trust an edited merged file.
    from reconcile_migration_reports import merge_verified_reports
    report_rows=merge_verified_reports(read_json(old/'reports.json'),read_json(new/'reports.json'))
    for table,entry in plan.items():
        if not re.fullmatch(r'[a-z_]+',table) or not entry['keys']: raise ValueError('Unverified table/key')
        if not set(entry['columns'].values()) <= TYPES: raise ValueError('Unsupported column type')
        if not set(entry['keys']) <= entry['columns'].keys(): raise ValueError('Unknown primary key')
        rows=report_rows if table=='reports' else read_json(entry['path'])
        for row in rows:
            if not row.keys() <= entry['columns'].keys(): raise ValueError('Unknown data column')
        entry['rows']=rows
    return plan


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--private-dir',type=Path,required=True)
    p.add_argument('--apply',action='store_true')
    p.add_argument('--confirm-target')
    args=p.parse_args()
    plan=build_plan(args.private_dir)
    summary={table:len(entry['rows']) for table,entry in plan.items()}
    if not args.apply:
        print(json.dumps({'mode':'dry-run','schema':SCHEMA,'tables':summary}));return
    if args.confirm_target!=TARGET: p.error('Explicit target confirmation required')
    cfg={}
    for line in (args.private_dir/'target.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1);cfg[k.strip()]=v.strip().strip('\"').strip("'")
    if cfg.get('TARGET_PROJECT_REF')!=TARGET: raise ValueError('Wrong project')
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb
    with psycopg.connect(host='db.'+TARGET+'.supabase.co',dbname='postgres',user='postgres',
                         password=cfg['TARGET_DATABASE_PASSWORD'],sslmode='require',connect_timeout=15) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='120s'")
            cur.execute("SET LOCAL lock_timeout='5s'")
            cur.execute('SELECT pg_advisory_xact_lock(20261125)')
            cur.execute('CREATE SCHEMA {} AUTHORIZATION postgres'.format(SCHEMA))
            cur.execute('REVOKE ALL ON SCHEMA {} FROM PUBLIC, anon, authenticated, service_role'.format(SCHEMA))
            for table,entry in plan.items():
                target=sql.Identifier(SCHEMA,table)
                columns=list(entry['columns'])
                definitions=[sql.SQL('{} {}').format(sql.Identifier(k),sql.SQL(entry['columns'][k])) for k in columns]
                definitions.append(sql.SQL('PRIMARY KEY ({})').format(sql.SQL(',').join(map(sql.Identifier,entry['keys']))))
                cur.execute(sql.SQL('CREATE TABLE {} ({})').format(target,sql.SQL(',').join(definitions)))
                cur.execute(sql.SQL('ALTER TABLE {} ENABLE ROW LEVEL SECURITY').format(target))
                cur.execute(sql.SQL('REVOKE ALL ON {} FROM PUBLIC, anon, authenticated, service_role').format(target))
                with cur.copy(sql.SQL('COPY {} ({}) FROM STDIN').format(target,sql.SQL(',').join(map(sql.Identifier,columns)))) as copy:
                    for row in entry['rows']:
                        copy.write_row([Jsonb(row[k]) if entry['columns'][k]=='jsonb' and row.get(k) is not None else row.get(k) for k in columns])
                cur.execute(sql.SQL('SELECT count(*) FROM {}').format(target))
                if cur.fetchone()[0]!=len(entry['rows']): raise ValueError('Target count mismatch')
                print(table+': validated '+str(len(entry['rows'])),flush=True)
            cur.execute("SELECT has_schema_privilege('anon', %s, 'USAGE'),has_schema_privilege('authenticated', %s, 'USAGE'),has_schema_privilege('service_role', %s, 'USAGE')",(SCHEMA,SCHEMA,SCHEMA))
            if any(cur.fetchone()): raise ValueError('Unexpected schema access')
        # Commit happens only after every table and role check succeeds.
    print(json.dumps({'status':'rehearsal_committed','schema':SCHEMA,'tables':summary,'production_ready':False}))


if __name__=='__main__':
    main()
