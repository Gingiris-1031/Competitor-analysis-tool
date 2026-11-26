# Analook migration to the new Supabase project

Target: `miscpkgclgixmqjftscl`. Source-code baseline: remote main
`db435eb19b658b1d665c03c36b7ac8d977afbcb3`, fetched 2026-11-24.
Business data cutover completed on 2026-11-25; final independent site acceptance is recorded below. Legacy Supabase Auth is intentionally retained.

## Verified boundaries

- The canonical local checkout was stale (September); this independent clone uses current remote main.
- Application is FastAPI with static browser authentication, not Next.js.
- The new project's public schema was empty when inspected in Chrome.
- InsForge public table inventory: account_profiles, account_credit_ledger,
  internal_cache, mcp_accounts, mcp_api_keys, reports, scorecards, timelines.
- InsForge REST exact count observed: 952 reports. This is a dated observation, not a cutover baseline.
- CLI SQL/data/schema export requests returned HTTP 502. A single-page REST GET succeeded.
- Fly CLI login completed as the existing user. Production config still uses
  old Supabase and InsForge, with InsForge Auth rollout set to canary.
- Both sources' business rows have now been exported and local checksums verified.
- New target SQL credentials were supplied locally and verified on 2026-11-25.

## Source ownership and merge rules

| Domain | Candidate authoritative source | Required validation |
|---|---|---|
| Auth users/identities | Old Supabase | Export auth schema through supported project migration; retain UUIDs; validate passwords/OAuth separately |
| Profiles, live credit balance, payment attribution | Old Supabase | Confirm deployed configuration and final source values; InsForge mirror must not overwrite newer balances |
| Reports | Union of both databases | Preserve IDs, owner, visibility and content; review every differing row; never pick by timestamp alone |
| Scorecards, timelines, MCP accounts/keys | InsForge | Preserve key hashes, owners, expiry/revocation, balances, private flags |
| Credit ledger/account mirror | InsForge | Preserve as audit history; do not replay ledger as credit grants |
| Other old Supabase tables | Old Supabase schema inventory | Include API keys, promo redemption, payment idempotency, autopilot, caches and QA if present |
| Files | Both storage inventories | Export actual objects, not only storage metadata; verify checksums |

## Tools prepared

`scripts/export_insforge_for_migration.py` performs GET-only keyset pagination.
It requires exact before/after counts, rejects duplicate keys, writes 0600 files
in a fresh 0700 directory, and maintains a manifest with SHA-256 hashes.
It does not export schema/Auth/files and does not claim snapshot consistency.
In-place updates during export cannot be detected from counts alone: repeat
under a write pause or obtain a database-consistent snapshot before cutover.

`scripts/reconcile_migration_reports.py` compares two JSON row arrays offline.
It reports union membership and conflicting field names without printing data.
Exit code 2 means conflicts require review. It cannot import or overwrite rows.

`merge_verified_reports()` additionally supports a conservative local merge:
union missing columns and an absent `_translations` cache only. Any conflicting
shared business value stops the merge. No timestamps are used to pick a winner.

`scripts/export_old_supabase_via_fly.py` discovers tables through the source
OpenAPI and exports through the existing container credentials. Large tables
stream page envelopes with a completion marker to avoid accumulating an entire
report table in production memory. Credentials never leave the container.
The first bulk report attempt ended with SSH process status 4294967295; the
streamed retry completed at 561 rows. No cause for that exit was established.

## Completed first-pass reconciliation (2026-11-24)

- InsForge: reports 952, account_profiles 647, account_credit_ledger 306,
  scorecards 6, timelines 2, mcp_accounts 3, mcp_api_keys 3, internal_cache 1.
- Old Supabase: profiles 659, reports 561, promo_codes 1, promo_redemptions 33,
  audit_cache 518, audit_qa 5; all four autopilot tables and wayback_cache empty.
- Old Auth Admin API: 661 users, no password hashes. Two Auth users have no
  profile; every profile has an Auth user. Preserve those two identities too.
- InsForge Auth: 1 user, 0 user_providers, 1 account profile identity binding;
  private local exports saved. Do not silently drop the canary identity.
- All 647 mirrored profile IDs exist in the old source; 12 source profiles are
  missing in the mirror. Do not use the mirror as the user/credit authority.
- All 561 old report IDs are in InsForge, plus 391 InsForge-only IDs. Shared
  owner, visibility, markdown, status, URL and product name values are identical.
- All 561 have schema-only differences (`completed_at`, `credits_cost`,
  `updated_at`); one also has an absent `_translations` cache. Conservative merge
  produced 952 rows preserving both sources' fields and the translation cache.
- Both sources have zero Storage buckets, verified through authenticated APIs.
- 13 offline exporter/reconciliation tests passed. No target import performed.
- Source columns (66), constraints (18) and two key InsForge function definitions
  saved separately; a complete SQL schema backup is still not available.

Private output `merged-reports-review.json` is a review payload, not proof that
the target schema accepts every column. Data counts are snapshots while writes
continue. The old export is public REST-visible data plus Auth metadata; it
does not prove that hidden schemas/tables, cron jobs, triggers or all grants
have been backed up.

## Access and billing next steps

The local 0600 file `target.env` under the private backup directory now contains
the target database password. A direct TLS connection succeeded on 2026-11-25.
The server API secret field remains empty; no credential values are in this repo.

Original Supabase password hashes are absent from Auth Admin responses. A
supported full auth-schema export needs old database/management access. If
that cannot be recovered, choose an explicit staged legacy-Auth strategy or
a tested account-preserving reset/OAuth migration; do not promise existing
password continuity from an Admin API user export.

Pricing checked at https://supabase.com/pricing on 2026-11-24: Pro starts at
$25/month with a first Micro project covered by compute credits and daily
backups retained seven days. Free includes a 500 MB database and no automated
backups. Export JSON bytes are not database size. No payment/plan change made.

Private exports belong outside this repository, under
`/Users/iriscarrot/Downloads/analook-migration-private-20261124/`.
Do not commit or upload backup files or credentials.

## Schema and application work remaining

1. Obtain live schemas from both sources. Repository SQL is incremental and is
   not a complete base schema: do not apply all migrations blindly.
2. Replace InsForge-specific `system.update_updated_at()` dependencies with an
   explicit reviewed target function. Validate target role grants, RLS and
   service_role execution of RPCs. Do not import InsForge platform schemas into
   Supabase Auth.
3. Restore business data and merge InsForge-only data after conflict review.
   The approved interim plan retains old Supabase Auth. Preserve user UUIDs
   without target auth.users foreign keys; verify identity on the backend.
   Recover old password hashes if management access becomes available.
   Any later Auth migration requires SMTP/OAuth/redirect and session testing.
4. Route existing InsForge-backed report, timeline, MCP and cache calls to the
   new Supabase REST/RPC endpoints. Disabling InsForge variables alone leaves
   direct InsForge callers broken. Keep Auth rollout off until verified.
5. During the interim plan, retain old Auth URL/key in static pages and
   SUPABASE_URL/SUPABASE_SERVICE_KEY. Set the new server-only business pair
   SUPABASE_DATA_URL/SUPABASE_DATA_SERVICE_KEY only after target readiness.
   Replace browser Auth configuration only in the later Auth migration.
6. Test signup/login/reset/OAuth, existing-user UUID ownership, private/public
   reports, balance debit under concurrency, payment retry idempotency,
   redemption, MCP limits/revocation, background jobs and Storage links.
7. Quiesce new writes/jobs/payment processing with a replay-safe plan, take a
   final consistent export, reconcile counts/content/foreign keys, and switch.
   Resume only after smoke tests. If rollback follows target writes, reconcile
   them back first; simply reverting URLs can lose new data/payments.

## Release gate

An isolated rehearsal import into the new project has been performed; no
public/Auth schema mutation, production secret change, or traffic cutover has
been performed. Before deployment run the repository-required
source verification and relevant tests, review the exact config/commit, and
obtain site-qa PASS against the production URL before reporting completion.

## Target rehearsal verified on 2026-11-25

`scripts/rehearse_supabase_import.py` rebuilt a plan from checksum-verified
backups, then transactionally created and populated 18 typed tables under
`analook_migration_20261125` in the new project. This schema is intentionally
not the production schema: defaults, foreign keys, business checks, triggers,
RPCs, production grants and Auth integration remain to be completed. Missing
source fields are NULL here, not fabricated business defaults. Original JSON
exports retain the distinction between missing fields and explicit nulls.

All primary keys and source row counts passed. An independent connection then
verified all 659 profile balances, usage, quotas and plan types; four complete
report samples (including translation content); zero report-owner orphans;
RLS enabled on all 18 tables; and no schema USAGE for anon, authenticated or
service_role. Public schema remains empty. Database size at readback was
45,602,483 bytes. No billing change was needed for this rehearsal.

The local test suite for migration tools passed 17 tests. Evidence is saved
privately in `target-rehearsal-verification-20261125.json` alongside the backups.
The data remains the November 24 snapshot, not a final November 25 cutover copy.

## Approved interim Auth plan and local implementation

User approved bounded investigation of old database access, then retaining old
Supabase Auth while moving business data. Password resets are a fallback, not
authorized bulk email delivery. Browser access to the old dashboard remains
unverified following a browser-control interruption; this does not establish
that the user lacks access.

Local code now separates Auth and data clients, routes legacy InsForge business
REST/RPC calls to the optional new data backend, and retains token verification
against the old providers. Missing target profiles can be copied by exact UUID
from the old source with conflict-ignore inserts; existing target credits are
never overwritten by this bootstrap path. Payment email lookup uses profiles,
and Auth admin lookups still use the old Auth client. The legacy migration
endpoint is blocked in split mode. No flags have been enabled in production.

Thirty focused tests passed (21 migration tests and 9 split-client tests).
These are local tests, not live end-to-end acceptance. Target secret API key,
complete production schema/RPCs/grants, final snapshot and cutover validation
remain outstanding. No password reset email or identity reassignment occurred.


## Production business-data cutover — 2026-11-25

The new public schema contains 18 tables with RLS, server-only table grants,
verified constraints/defaults and deduct_credit, consume_mcp_credit,
link_insforge_identity and public_report_gallery_rows functions. A rollback-only
full-data trial passed before creating the production schema. Real application
SDK/REST reads and gallery RPC passed against the target secret API key.

Both Fly instances were gated using maintenance flags and reported zero active
analysis/audit jobs before the final source exports. Original Supabase Auth
remained active; new profiles created there after export bootstrap into the
target by exact UUID without overwriting target balances.

Final source snapshots are privately stored under final-20261125. Both manifests
are complete and checksum-verified. Final data was applied transactionally as
differences against the previously verified baseline: 660 profiles, 953 reports,
648 account mirrors, 307 ledger events, three MCP accounts and keys, six
scorecards and two timelines. No source deletions were observed. The old Auth
export contains 662 identities, including two without profiles. Auth identities
and passwords were not recreated or reset.

Both Fly machines (d891e035c95738 and 85e273f4167dd8) independently verified:
- SUPABASE_DATA_URL points to miscpkgclgixmqjftscl;
- SUPABASE_URL still points to nkunysycqapregxubcil;
- target profile/report/ledger counts match the final export;
- old Auth admin identity lookup succeeds;
- gallery RPC works and debit for a nonexistent user returns false.

ANALOOK_INSFORGE_AUTH_ROLLOUT is off and INSFORGE_REPORTS_DUAL_WRITE is false.
Business calls route to new Supabase. Old source credentials/backups remain for
recovery, not as active business storage. ANALOOK_MIGRATION_MAINTENANCE is 0;
per-machine temporary flags were removed. Public health and gallery return 200.

A pre-existing missing privacy check on classic report APIs was discovered
while preparing acceptance. Split-backend deployments now verify persisted
report visibility before serving cached or stored payloads. Anonymous access
to a purpose-built private fixture returns 403. The full local test suite
passed 93 tests, including private/public/owner access rules.

The deployed source is preserved in this isolated checkout. On 2026-11-26,
the user approved committing and pushing this reviewed migration as one
release commit. This commit archives the already-deployed implementation.
No Supabase billing upgrade was performed. Legacy Auth retirement remains a
separate follow-up; this cutover completes the approved business-data stage.


## Independent production acceptance: PASS

Site QA verified the real www.analook.com URLs after maintenance was lifted:
health and strict health 200; English/Chinese homepages 200 with correct lang
and legacy Auth URL; gallery 200 with 60 public rows; classic report 00299e75
with 20 non-empty sections; audit ga-17b7ecc0 with three non-empty reports;
corresponding share pages 200. Eight private-fixture payload/export/share/page
paths returned 403. Evidence: qa/public-results.json and qa/private-results.json
in the private backup directory. Interactive login, actual payments and new
AI report generation were deliberately not performed. The disposable private
fixture was removed after acceptance; it is not part of migrated user data.
