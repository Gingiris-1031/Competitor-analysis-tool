"""Generate a reviewable server-only production schema from exported metadata.

Does not connect or apply. Requires the verified export directory. Auth stays
in the original project: no target auth.users foreign keys or browser grants.
"""
import argparse
import json
from pathlib import Path
from rehearse_supabase_import import build_plan, read_json


def ident(value):
    return '"' + value.replace('"', '""') + '"'


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def old_default(prop):
    value = prop['default']
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if value in ('now()', 'gen_random_uuid()', "(now() + '00:01:00'::interval)"):
        return value
    return literal(value)


def generate(root):
    plan = build_plan(root)
    old = read_json(root / 'old-supabase-rows-01/openapi.json')['definitions']
    source_columns = read_json(root / 'insforge-columns.json')['rows']
    source_constraints = read_json(root / 'insforge-constraints.json')['rows']
    statements = ['-- Generated from observed source metadata; review before applying.',
                  'SET LOCAL search_path = public, pg_catalog;']
    for table, entry in plan.items():
        definitions = []
        required = set(old.get(table, {}).get('required', []))
        for name, kind in entry['columns'].items():
            prop = old.get(table, {}).get('properties', {}).get(name, {})
            col = next((c for c in source_columns if c['table_name'] == table and c['column_name'] == name), None)
            default = old_default(prop) if 'default' in prop else None
            if col and default is None:
                default = col.get('column_default')
            # Keep historical rows that never had this column nullable; new
            # inserts still receive the verified source default.
            nullable = any(row.get(name) is None for row in entry['rows'])
            nonnull = (name in required or (col and col['is_nullable'] == 'NO')) and not nullable
            definitions.append(ident(name) + ' ' + kind + (' DEFAULT ' + default if default else '') + (' NOT NULL' if nonnull else ''))
        definitions.append('PRIMARY KEY (' + ','.join(map(ident, entry['keys'])) + ')')
        statements.append('CREATE TABLE public.' + ident(table) + ' (\n  ' + ',\n  '.join(definitions) + '\n);')
        statements.extend(['ALTER TABLE public.' + ident(table) + ' ENABLE ROW LEVEL SECURITY;',
                           'REVOKE ALL ON public.' + ident(table) + ' FROM PUBLIC, anon, authenticated;',
                           'GRANT SELECT, INSERT, UPDATE, DELETE ON public.' + ident(table) + ' TO service_role;'])
    for c in source_constraints:
        if not c['definition'].startswith('PRIMARY KEY'):
            statements.append('ALTER TABLE public.' + ident(c['table_name']) + ' ADD CONSTRAINT ' + ident(c['conname']) + ' ' + c['definition'] + ';')
    statements.append('ALTER TABLE public.promo_redemptions ADD CONSTRAINT promo_redemptions_user_code_key UNIQUE(user_id, code);')
    for table, definition in old.items():
        for name, prop in definition['properties'].items():
            import re
            match = re.search(r"<fk table='([a-z_]+)' column='([a-z_]+)'/>", prop.get('description', ''))
            if match:
                target, column = match.groups()
                statements.append(f'ALTER TABLE public.{ident(table)} ADD FOREIGN KEY ({ident(name)}) REFERENCES public.{ident(target)}({ident(column)});')
    for fn in read_json(root / 'insforge-functions.json')['rows']:
        statements.append(fn['definition'].rstrip() + ';')
    gallery = (Path(__file__).resolve().parents[1] / 'migrations/20260827130000_create-internal-cache.sql').read_text()
    statements.append(gallery[gallery.index('CREATE OR REPLACE FUNCTION'):])
    statements.append('''CREATE FUNCTION public.deduct_credit(p_user_id uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
 UPDATE public.profiles SET credits_balance=credits_balance-1,
 credits_used=credits_used+1, updated_at=now()
 WHERE id=p_user_id AND credits_balance>=1;
 RETURN FOUND;
END; $$;
REVOKE ALL ON FUNCTION public.deduct_credit(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.consume_mcp_credit(text,integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.link_insforge_identity(uuid,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.deduct_credit(uuid), public.consume_mcp_credit(text,integer), public.link_insforge_identity(uuid,text), public.public_report_gallery_rows() TO service_role;
CREATE INDEX reports_user_created_idx ON public.reports(user_id, created_at DESC);
CREATE INDEX reports_public_created_idx ON public.reports(created_at DESC) WHERE is_public=true;
CREATE INDEX mcp_api_keys_owner_created_idx ON public.mcp_api_keys(owner_id,created_at DESC);
CREATE INDEX profiles_email_idx ON public.profiles(email);
NOTIFY pgrst, 'reload schema';''')
    return '\n\n'.join(statements) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(generate(args.private_dir))
    print('Reviewable schema written; no database changes applied.')
