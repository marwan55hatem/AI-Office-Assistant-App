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

## Phase 2: the desktop app uses the online database

**Backend** (migration `0002`)
- New endpoints: `POST /sessions/sync` (idempotent batches of sessions and events), `GET /sessions`,
  `/sessions/{id}`, `/sessions/{id}/events`, `GET /stats/today`, `/stats/range`, `/events/recent`,
  `/tasks` (+ toggle, deadline, delete), `/calendar` (+ attendees), `/ai/chats` (+ messages),
  `/documents`, `PATCH /users/me`, `POST /auth/change-password`, `GET /users?role=`.
- Sessions use the id the desktop app generates (so it can record offline) and store the employee's
  local date, so "today" and "last 7 days" are counted in local days as before. A session counts as
  running only while the app sent data in the last 2 minutes, so a crashed app does not stay "working".
- Events carry a client id: a batch sent twice is stored once. Counters only grow.
- New tables `ai_chats` and `ai_messages` (private to their owner, even from managers), with RLS.
- Rules: employees see and create only their own tasks and cannot delete assigned ones; only managers
  write calendar events and documents; managers-only documents never reach employees.
- Fix: presenting a refresh token that was revoked by sign-out or a password change no longer ends
  the user's other sessions; only a reused *rotated* token does (theft detection).

**Desktop app** (new `cloud/` package)
- `RemoteDatabase` offers the same methods and return shapes as `DatabaseManager`, so the screens
  barely changed; `main.App` picks it unless `OFFICE_BACKEND=local`. Server address: `OFFICE_API_URL`.
- Sign-in with the work e-mail and password; the role comes from the account (the Manager/Employee
  toggle is gone). "Keep me signed in" stores only the refresh token, in Windows Credential Manager,
  and the app reopens signed in. Sign-out deletes it.
- Joining: the sign-up screen asks for the company code or an invite link.
- Work sessions record into a local outbox (`%LOCALAPPDATA%\OfficeAssistant\outbox.db`) and are sent
  every 5 seconds; running counters are sent every 5 seconds too, so managers see live numbers and a
  network drop loses nothing. Queued data is sent on exit.
- Offline banner; pages that need the server are greyed out; Session, AI Helper and Settings keep working.
- Ids are UUID strings online: the session page and the session history no longer assume numbers.

**Plain-text passwords removed**
- The local SQLite database now stores salted scrypt hashes and converts existing plain-text passwords
  on first start; password rows are never handed to the UI. Changing a password checks the current one
  in the database/server, not in the screen. Minimum length 8 (the server's rule).
- **The admin panel (`admin.py`, `admin_ui/`) was removed**, with its 10 tests and its program in the
  installer: it edited plain-text passwords in a local file that the online app no longer uses.
  Managers approve, disable and invite people in the app (and on the website, Phase 8).

**Tests**: backend 85 passed (1 skipped: the chat-engine check needs PyTorch on the server, Phase 3),
including the desktop client against the real API. Desktop 177 passed (167 − 10 admin + 20 new).
An end-to-end run of the real window against a running server passed 11/11 (sign-in for both roles,
every page, offline banner and recovery, remembered sign-in, sign-out). It found and fixed one bug:
the sync thread's stop flag hid a method of Python's `Thread`, so closing the app would have failed.

**Not done in this phase**: the user guide, README and install notes still describe the admin panel
and the role toggle; they are updated in Phase 9 as planned. The webcam session was exercised by tests
and the page's tick code, not by a live camera run.
