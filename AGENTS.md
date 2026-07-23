# AGENTS.md

## GitHub account safety red lines (P0)

These rules apply before any action that changes this repository or its GitHub
remote. Account safety takes priority over deployment speed and SEO cadence.

- The production source is `/Users/iriscarrot/code/Competitor-analysis-tool`,
  remote `Gingiris-1031/Competitor-analysis-tool`, branch `main`.
- Never reference or link the suspended legacy GitHub account. Use Analook,
  `gingiris.tools`, or `clawhub.ai/user/gingiris` for public references.
- Never enable GitHub Pages, create a daily GitHub Actions cron, create mirrors
  of legacy repositories, automate stars/follows, or mass-open external PRs.
- Batch planned changes into one human-reviewed commit and at most one push per
  release window. Do not generate daily SEO commits or push bursts.
- Use `Iris Wei <iris.wei@gingiris.com>`, a natural one-line commit message, and
  no AI/co-author trailer or generated multi-line commit body.
- Never force-push, rewrite published history, or push when local and remote
  history have diverged. Fetch and stop for review instead.
- Inspect the dirty worktree first. Stage explicit paths only; never use
  `git add .`, and never include unrelated user changes.
- Never commit credentials. Before committing, inspect the staged diff for
  tokens, keys, private files, unexpected account references, and generated
  artifacts.
- Immediately before a production commit or deploy, run
  `python3 scripts/verify_deploy_source.py`, relevant tests, and
  `git diff --cached --check`.
- Stay within the permanent behavioral limits: no batch writes across more
  than five repositories per hour, no more than ten commits per hour, and no
  more than one newly created repository per week.

<!-- INSFORGE:START -->
## InsForge backend

This project uses [InsForge](https://insforge.dev): an all-in-one, open-source Postgres-based backend (BaaS) that gives this app a database, authentication, file storage, edge functions, realtime, an AI model gateway, and payments through one platform.

- **Project:** **Analook** (API base `https://smk6dawe.us-east.insforge.app`)
- **Skills:** these InsForge skills are installed for supported coding agents. Reach for them before implementing any InsForge feature instead of guessing the API:
  - `insforge`: app code with the `@insforge/sdk` client (database CRUD, auth, storage, edge functions, realtime, AI, email, and Stripe payments).
  - `insforge-cli`: backend and infrastructure via the `insforge` CLI (projects, SQL, migrations, RLS policies, storage buckets, functions, secrets, payment setup, schedules, deploys).
  - `insforge-debug`: diagnosing failures (SDK/HTTP errors, RLS denials, auth and OAuth issues) and running security or performance audits.
  - `insforge-integrations`: wiring external auth providers (Clerk, Auth0, WorkOS, Better Auth, etc.) for JWT-based RLS, or the OKX x402 payment facilitator.
  - `find-skills`: discovering additional skills on demand.
- **Credentials:** app code reads keys from `.env.local`; the CLI reads `.insforge/project.json`. Never hardcode or commit keys.

Key patterns:

- Database inserts take an array: `insert([{ ... }])`.
- Reference users with `auth.users(id)`; use `auth.uid()` in RLS policies.
- For storage uploads, persist both the returned `url` and `key`.
<!-- INSFORGE:END -->
