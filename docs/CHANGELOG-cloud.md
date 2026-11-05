# Cloud upgrade changelog (branch `cloud-upgrade`)

## Phase 1: backend foundation and accounts

**Added** `backend/` — a FastAPI + PostgreSQL API (SQLAlchemy 2, Alembic), separate from the desktop app.

- **Tables** (all with `company_id` except `companies`): companies, users, invites, sessions, events,
  tasks, calendar_events, documents, ai_usage, meeting_requests, messages, notifications, email_log.
  Two more were needed: `calendar_attendees` (event invitations, as in the desktop app) and
  `refresh_tokens` (for refresh-token rotation, reuse detection and logout).
- **Accounts**: `POST /auth/register-company` creates the company and its manager; login, refresh
  (rotating, with reuse detection that revokes the whole session family), logout, `GET /auth/me`.
  Passwords are hashed with Argon2id. Access tokens last 15 minutes, refresh tokens 30 days.
- **Joining**: with a single-use invite link (bound to an e-mail if the manager entered one,
  expires after 7 days, stored only as a SHA-256 hash) or the company's 8-character join code.
  New accounts stay *pending* until a manager approves them. Managers can disable and
  re-enable accounts (disabling revokes their sessions at once) and rotate the join code.
- **Tenant isolation, two layers**: `TenantRepository` filters every query and stamps every insert
  with the company from the token; PostgreSQL Row-Level Security (`FORCE`d on every table) compares
  each row with a per-transaction setting. Foreign keys are composite `(company_id, id)`.
  The API refuses to start when its database role could bypass RLS.
- **Hardening**: login/register/join rate-limited per e-mail and per IP; all request bodies reject
  unknown fields (so `company_id`/`role` can never come from the client); CORS limited to the website
  origin; API docs switched off in production; no passwords, tokens or bodies are logged.
- `.env.example`, `docker-compose.yml` (local PostgreSQL), `Dockerfile`, `scripts/create_app_role.py`.

**Tests**: 66 backend tests — auth, roles, migrations (empty DB → head → base → head, and models
match the migration) and isolation (every route, every repository, RLS on every table). A deliberate
break of the repository filter was caught by 12 tests. The desktop app is unchanged; its 167 tests pass.

**Notes for later phases**
- The migration owner must be a superuser or have BYPASSRLS (login/join lookups are SECURITY
  DEFINER functions); the app role must have neither. Check this on the hosting provider in Phase 9.
- The rate limiter keeps counters in memory (one server process); use a shared store if the API is
  scaled to several instances.
- One account per e-mail address across the whole service.
