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

## Phase 3: the chat model runs online (Groq)

**Backend**
- `POST /ai/chat` streams an answer as server-sent events (`delta`, then `done` with the sources, or
  `error`). The app sends only `{chat_id, question}`; the **server builds the prompt**: the fixed
  instruction, the model's own earlier answers in that chat (never engine answers that contain data),
  and BM25 passages from the company's documents the user may read (managers-only documents are left
  out *before* searching for employees). The model never sees tasks, calendar, sessions or team data.
- `GET /ai/status`: whether the model is set up, today's usage and budget, what is and is not sent.
- Provider: Groq's OpenAI-compatible API, model `openai/gpt-oss-120b` (config `GROQ_MODEL`), key only in
  the server environment (`GROQ_API_KEY`). Streaming; reasoning text switched off; rate limits and
  server errors retried with backoff honouring `retry-after` (3 attempts) before the first token; if
  the provider refuses an optional field the request is retried without it. Only status codes are
  logged, never prompts or answers. Without a key the endpoint answers 503 and the app falls back.
- **Budget**: tokens per company per UTC day (`AI_DAILY_TOKEN_BUDGET`, default 100,000) recorded in
  `ai_usage`; when used up, 429 with "Your company has used today's AI allowance…". Usage is recorded
  even when the user presses Stop. Per-user limit: 10 questions per minute.
- **Instruction-injection guard** (new — the brief said "keep" it, but none existed): document passages
  go inside `<<<DOCUMENT … DOCUMENT>>>` fences that the system instruction says are data, never orders;
  chat-template tokens are removed, fence markers inside a document are defused, role lines such as
  `system:` are quoted, and passages that look like instructions are labelled for the model.
- The database work of a chat request finishes before streaming starts, so no transaction stays open
  while the model writes.
- `AI_FAKE_MODEL=1` (development only, ignored in production) answers with a fixed text, for testing
  without a key.

**Desktop app**
- The intent engine still runs in the app and decides routing exactly as before (data questions are
  answered from the database through `RemoteDatabase`); general and document questions are streamed
  from `/ai/chat`. Stop closes the connection, which also stops the server. The sources shown under an
  answer are the ones the server really used.
- When the model cannot answer (offline, busy, daily allowance), the chat shows the engine's own answer
  or the matching passages plus a short note saying why.
- Header badge: *AI model: online / offline — needs a connection / off*.
- Settings → AI assistant: the on/off switch, the list of what is sent and what is never sent, and the
  note that Groq may keep request logs for up to 30 days for troubleshooting or abuse checks under its
  terms (Groq keeps no inference data by default; Zero Data Retention can be enabled in Groq's console).
- **Removed** the local Qwen2.5-1.5B model: its loader (`llm/model_manager.py`), config, self-test, the
  "free the memory" button, the download entry in `tools/fetch_models.py`, the `qwen2` build hook, the
  self-check step, and the 2.9 GB model folder. Models bundled with the app: 7.9 GB → 5.0 GB.

**Tests**: backend 102 passed (1 skipped as before), including 17 new AI tests (stream, prompt contents,
history rules, refusals, budget, rate limit, injection fence, Groq parsing/retries). Desktop 182 passed
(5 new: streaming worker, errors and limit, offline, routing request, Settings notice; one chat-screen test
now checks that only the chat id and question are sent). Live end-to-end run of the real chat screen
against a running server with the stand-in model: 7/7.

**Live smoke test against Groq (2026-11-06, real key, `openai/gpt-oss-120b`): passed.** Provider call:
first token after 0.6 s, correct answer, real token counts. End to end (real chat screen -> real server ->
real Groq), 8/8: document question answered correctly with its source (48 hours), a managers-only
document's secret was not revealed to an employee, a general question answered, a data question answered
from the database, and real token usage recorded (3 requests, 1,064 tokens in, 223 out). The key appeared
in no log. Observation: the model writes citations like 【policy.md】 in its own style next to the
app's "Sources:" line (cosmetic).

**Still open**: the new installer and its measured size (Phase 9 rebuild); `THIRD_PARTY_NOTICES.md` and the docs still list
Qwen (Phase 9).

## Phase 4 — Manager reports with graphs and analytics

**Backend** (`backend/app/services/reports.py`, `routers/reports.py`): `GET /reports/overview`,
`/reports/trends` (day or week buckets) and `/reports/employee/{id}`, all for a date range (max 366 days).
Metrics: focus / distracted / away %, hours worked, daily and weekly trends, per-employee ranking
(paginated, sortable), most-used apps, task completion rate, attendance by day, employee vs team average,
and change against the previous period of the same length.

Definitions: hours worked = focus + distracted time; tasks completion = tasks created in the range that
are done; attendance = at least one session that day; days are the employee's local dates; only active
employees count. A change is shown only when both periods have data ("no earlier data" otherwise, never a
fake 0 % or "+100 pts").

**Cache**: in-process, 30 s, one entry per company and query; cleared on task and people writes (not on
session syncs, so a figure can be up to 30 s old).

**App usage (new data)**: the desktop records the *program name* of the window in front (from the process
image, never the window title) and syncs per-session seconds per app (`session_apps` table, migration
`0003_phase4_session_apps`, row-level security like every tenant table). The privacy text must say that
app names now reach the server (Phase 9). Video and screenshots still never leave the PC.

**Desktop**: the old weekly-report card is replaced by a Reports page (online only): filters (period,
custom dates, employee), six KPI cards with change arrows, focus line chart (with team average for one
employee), stacked hours, ranking bars, attendance, app donut, sortable paginated table, drill-down by
double-click, export to CSV (formula-injection safe) and PDF. Charts are drawn with QPainter (no new
dependency) and follow the light/dark theme. Screenshots: `screenshots_redesign/cloud/phase4_*`.

**Tests**: backend 130 passed (1 skipped), 28 new report tests with seeded data for each metric plus
isolation sweeps; desktop 215 passed (19 app-usage + 14 charts/export/page tests). Real-window run against
a live server with 12 seeded employees: 18/18 checks, 0 warnings.

## Phase 5 — E-mail notifications

**What is e-mailed**
- An **urgent task** a manager gives an employee: always sent (it cannot be turned off).
- **Meetings**: an invite when someone is added, a change when the title, date or time changes (a new
  description alone is not e-mailed), and a cancellation when the meeting is deleted or the person is
  removed. These are optional: each user can turn them off in Settings → Notifications. The person who
  made the change is never e-mailed about it.
- Each e-mail has the title, the time, who did it, and a link to the website (`APP_LINK_URL` + `/tasks` or
  `/calendar`), plus a note that the desktop app opens it too. HTML and plain text, in **English or Arabic**
  (right-to-left), chosen by the user (Settings → E-mail language).

**How it works**
- Providers behind one interface, chosen by `EMAIL_PROVIDER`: `smtp`, `resend`, `sendgrid`, `console`
  (development: logs a masked address only), `off`, `fake` (tests; refused in production). Keys only in
  the server environment (`backend/.env.example` lists them).
- `email_log` is the queue. The row is written in the same transaction as the task or meeting change, so
  nothing is queued for a change that was rolled back. A background worker in the API process sends due
  rows every `EMAIL_POLL_SECONDS` (10 s), one per transaction with `FOR UPDATE SKIP LOCKED` (no double
  send between workers). Retries after 1 min, 5 min, 30 min, 2 h, up to `EMAIL_MAX_ATTEMPTS` (5); refused
  addresses / bad keys fail at once. Resend gets an idempotency key so a repeat after a crash is dropped.
- Every decision is in the log: sent, failed, or skipped (turned off by the user, user no longer active,
  e-mail switched off on the server). The address and the body are never stored; the template data
  (title, time, who) is kept only until the e-mail is done, then emptied. Error texts are written by the
  server (status codes, kinds), never copied from the provider, which can echo the address.
- The worker sees one company at a time (RLS): a new `SECURITY DEFINER` function `email_due_companies`
  returns only the ids of companies with e-mail due.
- New: migration `0004_phase5_email` (user `email_notifications`, `language`; log `payload`, `urgent`,
  `next_attempt_at`), `PATCH /users/me/preferences`, `GET /email-log` (managers, no addresses),
  `scripts/send_test_email.py` for the real test e-mail.

**Desktop**: Settings has a Notifications card (meeting e-mails on/off, e-mail language), shown only when
signed in online.

**Tests**: backend 162 passed (1 skipped), 32 new: each trigger, opt-out (also for e-mails already
queued), disabled users, Arabic, retries and backoff, permanent failure, giving up, an unexpected error
not stopping the round, two companies in one round, the log endpoint (managers only, no addresses, per
company), every template × language (escaping), and each provider against a fake HTTP/SMTP server.
Desktop 218 passed (3 new). Live run against a real server with its own background worker: 6/6, and the
server log contained no address or title.

**Real test e-mail (2026-11-09): passed.** Through Resend (sandbox sender `onboarding@resend.dev`) to the account owner's address with `scripts/send_test_email.py`: an English urgent-task e-mail and an Arabic meeting invite, both accepted by Resend (message ids recorded in the run). The key stayed in `backend/.env`; neither it nor the full address was printed.

## Phase 6 — Meeting requests

**Lifecycle** (`/meeting-requests`, the server decides what is allowed):

| Step | Who | New status |
|---|---|---|
| Ask: topic, short note, 1-3 proposed times, length (15-240 min) | employee | pending |
| Accept one proposed time → a calendar event for both | manager | accepted |
| Decline, with a reason (required) | manager | declined (final) |
| Propose other times (1-3, optional note) | manager | rescheduled |
| Pick one of the manager's times → calendar event | employee | accepted |
| Cancel an open or accepted request (the event is removed) | employee | cancelled (final) |
| Cancel an accepted meeting | manager | cancelled (final) |

- Times are ISO date-times with the person's UTC offset; the same instant written in another offset
  counts as the same time. The calendar event uses the wall-clock time in that offset; a meeting that
  runs past midnight gets no end time. Times must be in the future, different, and within a year.
- The request row is locked while it changes (`FOR UPDATE`), so a second answer gets 409 instead of
  two bookings. Employees see only their own requests (404 for anyone else's), managers the company's.
- `GET /meeting-requests/waiting-count`: what waits for *you* (pending for a manager, rescheduled for an
  employee), shown as the Meetings badge.
- **Notifications**: every step notifies the other side in the app (`/notifications`: list, unread
  count, mark read / all read; private to their owner) and by e-mail (5 new English/Arabic templates;
  optional e-mails, so the "meeting e-mails" switch applies). A request to a named manager notifies
  only that manager, otherwise every active manager.
- Migration `0005_phase6_meeting_requests`: `duration_minutes`, `reply_note`, indexes for the status
  lists and unread notifications (the tables themselves were created in Phase 1).

**Desktop**: a **Meetings** page for both roles (sidebar, with a badge of what waits for you).
Employees fill in the request form (1-3 date-time pickers) and follow their requests; managers
accept a selected time, propose other times (dialog), or decline (reason dialog); either side can
cancel. The tray shows each new server notification once. The page is online-only (it explains this
when signed in to the local database). Radio buttons got a visible theme style. Fixed in passing: the
30-second auto-refresh no longer wipes the message of the last action.

**Tests**: backend 190 passed (1 skipped), 18 new: both full lifecycles, time zones, past midnight,
final states (409), every bad-time case, who may do what, isolation (another employee / company),
filters, a named manager, notifications privacy and read state, and the e-mails of each step.
Desktop 230 passed (12 new: both roles' buttons per state, dialogs, server refusals, offline, markup
escaping, the client's ISO times, tray notifications). Real-window run of the whole flow for both roles
against a live server with its own e-mail worker: 22/22 checks, 0 warnings. Screenshots:
`screenshots_redesign/cloud/phase6_*` (manager and employee, light and dark).

## Phase 7 — Chat between each employee and the manager

**Server** (`/chat`):
- One private conversation per employee, with every manager of the company (a shared inbox: any
  manager can answer). Other employees and other companies get 404 for it, like an unknown id.
- HTTP is the source of truth: `POST /chat/{employee}/messages`, paged history
  (`GET .../messages`: the latest 50, `before_id` for older, `after_id` to catch up), `POST .../read`,
  `GET /chat/conversations` (managers: unread first, then the most recent) and `GET /chat/unread-count`.
- **Live**: WebSocket `/chat/ws`. The access token is the first message (never in the URL, which ends up
  in logs); the socket closes with 4001 when the token expires and 4003 on a bad token. It pushes
  `message`, `delivered`, `read` and `typing` events. Pushes are sent only **after the commit**
  (a new SQLAlchemy after-commit hook), so nobody sees a message that was rolled back.
- **Delivered** = reached a device of the other side (pushed to an open connection, or fetched over
  HTTP); **read** = the other side opened the conversation.
- Limits: 4000 characters (control characters removed, empty refused), 10 messages per 10 s and 60 per
  minute per person (429).
- A new message creates one unread in-app notification per conversation (later messages update it);
  reading the conversation clears it. If the reader is offline, one `chat_unread` e-mail per conversation
  is queued for 10 minutes later (`CHAT_EMAIL_DELAY_MINUTES`) and skipped if by then the message was read
  or the person is online. The e-mail never contains the message text. The Settings switch now reads
  "E-mail me about meetings and unread messages".
- Limitation: live connections are kept in the API process, so this is for **one** server instance; more
  instances need a shared channel (PostgreSQL LISTEN/NOTIFY or Redis) behind `ChatHub.publish`. Clients
  lose nothing either way: they catch up over HTTP.

**Desktop**: a **Messages** page. Managers: the conversation list (unread counts, previews) and the chat;
employees: one chat with "your manager". Bubbles show Sent / Delivered / Read, the sender's name, and
"… is typing". Enter sends, Shift+Enter is a new line. The live channel (`cloud/chat_socket.py`, Qt's
`QWebSocket`) reconnects on its own (2 s, 5 s, 10 s, 30 s; at once with a fresh token after expiry); while
it is down the page polls every 5 s. The sidebar shows an unread badge; signing out closes the channel.

Fixed in passing: `ui.widgets.clear_layout` now also removes widgets inside nested layouts (old chat
bubbles were left behind when switching conversations), and a page-teardown crash caused by a Qt event
filter (replaced with a small `Composer` input class).

**Tests**: backend 206 passed (1 skipped), 14 new: ordering, paging both ways, isolation, conversation
order, read and delivered state, message rules, the flood limit, disabled accounts, notifications, the
delayed e-mail (no text, one per burst, skipped when read), the live channel (delivery, receipts, typing
only to the right people, no e-mail while online), bad/missing tokens, and closing on token expiry.
Desktop 241 passed (11 new). **Two-client check** (two real app windows, manager and employee, against a
live server): 21/21 checks in three runs in a row, 0 warnings. Messages arrive live in about 0.1 s, and
in about 7 s by polling when the live channel is down. Screenshots: `screenshots_redesign/cloud/phase7_*`.

## Phase 8 — Website

There is no separate "eighth update": the user confirmed on 2026-11-10 that it was a slip, so Phase 8 is
the website and Phase 9 the release.

**The site** (`website/`, Next.js 16, TypeScript, no UI or chart libraries):
- Public pages: Home, How it works (with app screenshots), Features, Privacy (what stays on the PC and what
  goes online), Download, Docs & FAQ, Sign up, Sign in. **English and Arabic** (`/en`, `/ar`, full
  right-to-left layout through logical CSS properties), chosen from the browser's language, with a switch
  that keeps the page. **Light and dark** themes (system default, remembered, no flash on load).
- **Download** reads the latest GitHub release on the server (cached for an hour): version, date, every
  file with its size, the total, the installer button, "View on GitHub", system requirements (Windows
  10/11, NVIDIA GPU recommended for summarise/translate). If GitHub cannot be reached it links to the
  releases page.
- **Sign up** creates a company and its manager through the API, or joins a company with its code or an
  invite link (pending until approved). **Signed-in area**: managers get Reports (KPIs with change,
  focus trend, hours per day, apps, ranking with sort, paging and drill-down to one employee, CSV export),
  Employees (approve/reject, enable/disable, company code, one-time invite links), Meetings and Messages;
  employees get Meetings and Messages. The chat is live (WebSocket) with polling while disconnected.

**Security**
- The browser never holds the long-lived token and never calls the API directly. The site's server keeps
  the tokens in **httpOnly, SameSite=Lax** cookies (Secure in production), forwards only allow-listed API
  paths (each path segment checked), and refreshes the session **once per token** — so parallel requests
  can never trip the API's refresh-token-reuse (theft) protection.
- State-changing calls must come from the site itself (same Origin plus a custom header); otherwise 403.
- The chat's socket gets a 15-minute access token from `/api/auth/socket` and sends it as its first
  message. Security headers: no framing, nosniff, strict referrer, camera/microphone/geolocation off.
- **API**: the website calls from one server, so the API now accepts the visitor's IP for its sign-in rate
  limits (`X-Client-IP`) — but only together with the shared `WEB_PROXY_SECRET` (constant-time compare).

**API fix found by the website tests**: with FastAPI's defaults, the request's transaction was committed
*after* the response was sent, so a client acting on an answer at once (signing in right after being
approved, reloading right after "Accept") could still see the old state. The request dependency now uses
`scope="function"`: the change is saved before the answer leaves. Also fixed: an old isolation test that
let the database pick "today" (UTC) and failed near midnight.

**Tests**
- Website: 26 Playwright tests, passing on three full runs in a row: every public page in both languages
  (lang/dir, one h1), language redirect and switch, theme memory, the Download page against the real
  GitHub release, sign-up → dashboard → download, sign out/in, wrong password, Arabic sign-in, join with
  code + approval on the web, invite link, cross-site refusals and the proxy allow-list, reports with
  seeded data (sort, paging, drill-down, CSV), meeting lifecycle on the web, chat between two browsers
  (live delivery and read receipts), disabling an employee. **Accessibility**: axe (WCAG 2.2 AA) on every
  public page in English and Arabic, light and dark, and on all signed-in pages: no serious or critical
  problems; a skip link reaches the content first.
- **Lighthouse** (local production build): desktop 100 / 100 / 100 / 100 (performance, accessibility, best
  practices, SEO) on Home, Download, Arabic Home and Features; mobile (simulated slow phone) performance
  79–95, the other three 100.
- Backend 209 passed (1 skipped), desktop 241 passed.
- Screenshots: `screenshots_redesign/cloud/phase8_*`.

**Still open**: the preview deployment needs a Vercel account and a publicly reachable API (Phase 9
deploys the API); error messages that come from the API are in English on the Arabic site.

## Website redesign and portal (Website_Build_Prompt.md, Design E)

**Design**: the site now follows **Design E "Spotlight Bento"** (`DesignE_dark.html` / `DesignE_light.html`),
compared with the references at 1440 px and 390 px in both themes: dot grid, sweeping spotlight, light-theme
blobs, rotating-beam cards, pill, gradient headings, the manager-report mock, the 6-card bento, live feed,
3 steps, privacy strip and call to action. Manrope + IBM Plex Mono + IBM Plex Sans Arabic via `next/font`.
Dark is the default; the system setting is followed on the first visit and the choice is remembered.
Motion stops for `prefers-reduced-motion` and while the tab is hidden; phones get the backdrop without
blur filters. The mock and the feed are labelled as example data. Arabic copy rewritten naturally, with the
Arabic project name المساعد المكتبي الذكي; the language choice is remembered.
Deliberate differences: some label colours are a little darker than the references (WCAG AA contrast), two
claims reworded to stay accurate ("each company's data is kept apart", "sync to your company's account"),
and the brief's Tailwind / next-intl / next-themes were not adopted — the existing tested theme and i18n
code already met every requirement (see `website/README.md`).

**New**
- **Forgot / reset password** (API + site): one-time link, stored only as a hash, valid 30 minutes, newest
  link only, always the same answer (no account discovery), signs the account out everywhere; always-sent
  e-mail in English or Arabic. Migration `0006_password_resets` (RLS + a SECURITY DEFINER lookup).
- **New passwords need 10 characters** (API, website, desktop app; existing passwords keep working).
- **Portal overview**: company, profile, desktop download card, members and approval status, and what waits
  for you (meetings, unread messages, this week's team focus).
- **Download**: disabled button with the reason when no release exists, `DOWNLOAD_URL` override, install steps.
- Styled **404 and error pages**; Open Graph image; canonical and hreflang (en/ar/x-default) per page.
- **Security**: a strict Content Security Policy with a fresh nonce on every page; the chat's WebSocket now
  refuses pages of other sites (Origin not in `CORS_ORIGINS`); every external link opens with
  `noopener noreferrer`; client and server form checks with errors announced to screen readers.
- **CI** (`.github/workflows/ci.yml`): website lint, type-check, unit tests, build; API tests on PostgreSQL.
  `website/PROGRESS.md` tracks the brief.

**Tests**
- Website: 36 Playwright end-to-end tests (all pass), incl. password reset through the real e-mail queue,
  form errors, 404, CSP, console errors, phone menu with no sideways scroll, and axe (WCAG 2.2 AA) on every
  public and portal page in English/Arabic and light/dark with no serious or critical problems. 28 unit
  tests (Vitest + Testing Library): forms, API client, validation, languages (Arabic has exactly the English
  keys), download card states, CSP.
- API: 218 passed (1 skipped), incl. password reset, the 10-character rule, the WebSocket origin check, and
  `password_resets` in the isolation sweep. Desktop: 241 passed.
- Lighthouse (local production build, simulated devices): desktop performance 96–100 and accessibility /
  best practices / SEO 100; mobile Home 84–93 (English, three runs; was 61 before the phone backdrop) and
  86–87 (Arabic), accessibility / best practices / SEO 100.
- Screenshots: `screenshots_redesign/cloud/phase8_*` (home 1440/390 light/dark, Arabic, download, portal,
  reports light/dark, meetings, messages, sign-up, forgot password, 404).

**Still open**: the preview deployment (Vercel + a public API) needs the owner's accounts (Phase 9); the CI
workflow runs once the branch is pushed; API error messages stay English on the Arabic site.
