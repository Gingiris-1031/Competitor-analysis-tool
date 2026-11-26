"""Replace the not-yet-live target baseline with a verified final export.

Run only under the deployed maintenance gate, before enabling target writes.
One transaction rolls back all tables on any failure. No Auth data is changed.
"""
import argparse
from pathlib import Path
from rehearse_supabase_import import build_plan, TARGET


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--snapshot',type=Path,required=True)
 p.add_argument('--credentials',type=Path,required=True)
 p.add_argument('--baseline',type=Path,required=True)
 p.add_argument('--confirm-target',required=True)
 p.add_argument('--maintenance-verified',action='store_true')
 a=p.parse_args()
 if a.confirm_target!=TARGET or not a.maintenance_verified:p.error('Target and maintenance confirmation required')
 plan=build_plan(a.snapshot);baseline=build_plan(a.baseline);cfg={}
 for l in a.credentials.read_text().splitlines():
  if '=' in l and not l.lstrip().startswith('#'):
   k,v=l.split('=',1);cfg[k.strip()]=v.strip().strip('\"').strip("'")
 assert cfg['TARGET_PROJECT_REF']==TARGET
 import psycopg
 from psycopg import sql
 from psycopg.types.json import Jsonb
 with psycopg.connect(host='db.'+TARGET+'.supabase.co',dbname='postgres',user='postgres',password=cfg['TARGET_DATABASE_PASSWORD'],sslmode='require',connect_timeout=15) as conn:
  cur=conn.cursor();cur.execute("SET LOCAL statement_timeout='300s'");cur.execute("SET LOCAL lock_timeout='10s'")
  cur.execute('SELECT pg_advisory_xact_lock(20261125)')
  for t,e in baseline.items():
   cur.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(t)));assert cur.fetchone()[0]==len(e['rows']), 'Target baseline changed'
  order=['profiles','account_profiles','promo_codes','autopilot_subscriptions','autopilot_snapshots','autopilot_diffs'];order += [t for t in plan if t not in order]
  for t in order:
   e=plan[t];cols=list(e['columns']);keys=e['keys']
   key=lambda r:tuple(r[k] for k in keys)
   old={key(r):r for r in baseline[t]['rows']}
   current={key(r):r for r in e['rows']}
   if old.keys()-current.keys():raise ValueError('Source deletions require review: '+t)
   rows=[r for k,r in current.items() if old.get(k)!=r]
   tmp='migration_stage_'+t
   cur.execute(sql.SQL('CREATE TEMP TABLE {} (LIKE public.{}) ON COMMIT DROP').format(sql.Identifier(tmp),sql.Identifier(t)))
   # Bounded COPY batches prevent a large report table hitting a statement timeout.
   for start in range(0,len(rows),25):
    with cur.copy(sql.SQL('COPY {} ({}) FROM STDIN').format(sql.Identifier(tmp),sql.SQL(',').join(map(sql.Identifier,cols)))) as copy:
     for r in rows[start:start+25]:
      copy.write_row([Jsonb(r[k]) if e['columns'][k]=='jsonb' and r.get(k) is not None else r.get(k) for k in cols])
   assignments=sql.SQL(',').join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(k),sql.Identifier(k)) for k in cols if k not in keys)
   cur.execute(sql.SQL('INSERT INTO public.{} SELECT * FROM {} ON CONFLICT ({}) DO UPDATE SET {}').format(sql.Identifier(t),sql.Identifier(tmp),sql.SQL(',').join(map(sql.Identifier,keys)),assignments))
   cur.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(t)));assert cur.fetchone()[0]==len(e['rows'])
   print(t+': '+str(len(e['rows']))+' verified; '+str(len(rows))+' changed',flush=True)
  cur.execute("SELECT count(*) FROM public.reports r LEFT JOIN public.profiles p ON p.id=r.user_id WHERE r.user_id IS NOT NULL AND p.id IS NULL");assert cur.fetchone()[0]==0
 print('Final data committed; ready for independently verified cutover.',flush=True)

if __name__=='__main__':main()
