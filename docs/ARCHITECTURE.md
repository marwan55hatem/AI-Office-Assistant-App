# Architecture

Version 2 has three parts:

| part | stack | role |
|---|---|---|
| **Desktop app** (this folder) | Python 3.12, PyQt5 | session tracking with local AI (camera, window, idle), every screen for employees and managers |
| **Online service** (`backend/`) | FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 17 | accounts, companies, all shared data, reports, e-mail queue, chat hub (WebSocket), AI Chat prompt to Groq |
| **Website** (`website/`) | Next.js 16 (App Router) | public pages (en/ar, dark/light), sign-up / sign-in / reset, the portal |

```
 Desktop app                                Website (Next.js)
   ui/ screens --> database/repositories       pages + route handlers ("BFF": tokens in httpOnly cookies)
                      |                                 |
                   cloud/ (RemoteDatabase, ApiClient,   | /api/proxy/* (allow-list), /api/auth/*
                   outbox, ChatSocket)                  |
                      |  HTTPS + WebSocket              |  HTTPS (+ X-Client-IP, shared secret)
                      +----------------+----------------+
                                       v
                    backend/app: routers -> services -> TenantRepository -> PostgreSQL
                    (JWT + refresh rotation)   (email worker, chat hub,       (Row-Level Security
                                                AI Chat -> Groq)               per company)
```

The desktop screens did not change their calls when the data moved online: they use the same
repositories, now backed by `cloud.remote_db.RemoteDatabase` (HTTP) instead of SQLite
(`OFFICE_BACKEND=local` keeps the old SQLite path for development).

## Desktop layers

```
                    main.py  (composition root)
                       |
        +--------------+---------------+
        v                              v
   ui/  (screens, widgets, theme)    detection/ (camera, screen, session timers)
        |        \
        |         +--> chat/  ----> assistant/ (intent engine)
        |                  \------> knowledge/ (BM25 search, local mode)
        |                   \-----> llm/ (the online model, through the service)
        v
   database/repositories  -->  cloud/ (online service)  |  database/db_manager (SQLite, local mode)
```

Rules of dependency (checked by the tests where possible):

* `ui/` depends on `database/`, `chat/`, `detection/`, `cloud/` -- never the other way round.
* `assistant/`, `chat/`, `knowledge/`, `detection/session.py`, `detection/categories.py` are **Qt-free**; they can be
  tested without a display (`tests/`).
* The UI calls named repository methods, never SQL or HTTP directly. On the service only the repositories
  run queries, and every company-owned table is filtered by `company_id` **and** protected by forced RLS.
* Heavy libraries (`torch`, `transformers`, `ultralytics`) are imported lazily, so the window opens fast.

## Module map

| package | files | responsibility |
|---|---|---|
| `main.py` | `App` | **composition root**: creates the remote (or local) database, builds the screens, navigation, tray notifier, logging; `--self-check` |
| `ui/` | `login_screen`, `signup_screen`, `auth_form` | authentication screens and their shared building blocks |
| | `employee_screen` (`SessionPage`, `EmployeeScreen`) | start/stop a session, live timers, camera preview, screen badges |
| | `manager_screen` (5 page classes + `ManagerScreen`) | employees, session history, tasks, reports; `ManagerHomeScreen` is the dashboard |
| | `todo_screen`, `calendar_screen`, `calendar_event_dialog` | tasks with deadlines; calendar |
| | `ai_helper_screen` | summarise (BART) and translate (Marian) |
| | `ai_chat_screen`, `chat_bubble`, `markdown` | the chat UI, message bubbles, safe Markdown + code blocks |
| | `knowledge_screen` | manager-only documents for the chat |
| | `settings_screen`, `preferences`, `theme` | profile/password/theme/AI switch; QSettings; the whole QSS design system |
| | `sidebar`, `shell`, `widgets`, `notifications` | navigation, shared shell behaviour, small helpers, tray notifications |
| `detection/` | `camera_thread`, `detector` | webcam loop + YOLO12n (person / phone) in a worker thread |
| | `screen_thread`, `screen_monitor`, `input_monitor` | active-window title -> category, keyboard/mouse idle time |
| | `session`, `categories` | the three timers and their priority rules (pure Python) |
| `assistant/` | `answers`, `intents`, `intent_model`, `lexicon`, `entities`, `playbooks`, `formatting`, `train_intent` | the data-driven chat engine and its trained intent classifier |
| | `summarizer`, `translator`, `extractors`, `ai_worker` | BART, MarianMT, PDF/text reading, background runner |
| `chat/` | `chat_client`, `backend_base`, `backend_local`, `backend_cloud`, `models`, `config` | the contract and its implementations; routing between engine / online model / documents |
| `llm/` | `service`, `workers`, `prompts`, `status` | the online model as the chat screen sees it: status, streaming from the service, stop |
| `cloud/` | `api`, `remote_db`, `reports_api`, `outbox`, `chat_socket`, `credentials`, `qt_bridge`, `config` | the client for the online service: tokens and refresh, repositories over HTTP, offline outbox for sessions, live chat (QWebSocket), Windows Credential Manager |
| `knowledge/` | `text`, `bm25`, `store` | chunking, BM25 ranking, documents + visibility |
| `database/` | `db_manager`, `repositories` | narrow repository views (used by every screen); the SQLite implementation for local mode |
| `tools/` | `code_audit`, `generate_database_docs` | maintenance scripts |
| `tests/` | test files + `conftest.py` | the desktop pytest suite |
| `backend/` | `app/routers`, `app/services`, `app/repositories`, `alembic/`, `tests/` | the online service (see `backend/README.md`) |
| `website/` | `src/app`, `src/components`, `src/lib`, `tests/`, `unit/` | the website (see `website/README.md`) |

## Data flows

### 1. A work session

```
CameraThread --detection_update(person, phone)--+
ScreenThread --screen_update(title, category)---+--> EmployeeScreen --> SessionState (3 timers)
ScreenThread --idle_update(is_idle, seconds)----+          ^
QTimer (1 s) ---------------------------------------- tick()  -> one second to exactly one of focus / distraction / away
                                                       |
                                       stop          -> outbox (on disk) -> POST /sessions  (totals, app names; retried when offline)
```

`SessionState` priority (first match wins): keyboard idle -> away; nobody in frame -> away; phone -> distraction;
distracting window -> distraction; idle window -> away; otherwise focus.

### 2. A chat question

```
AIChatScreen --> ChatClient --> LocalBackend.stream_reply
                                   |  1. AssistantEngine.ask(text)       (intent + the user's own data, from the service)
                                   |  2. document search on the service  (only when the engine is not sure)
                                   |  3. route:
                                   |       data question         -> engine text            -> typed into the bubble
                                   |       general / document    -> POST /ai/chat (stream) -> the service builds the prompt -> Groq
                                   |       model off / missing   -> engine text, or the quoted passages
                                   v
                 ReplyStream (kind "text" | "llm", source "engine" | "llm", sources [...])
```

The service builds the model's prompt from a fixed instruction, the model's **own** earlier answers in this chat and
the matching document passages the asker may read. It never receives tasks, calendars or team numbers, and each company
has a daily token budget (see [PRIVACY.md](PRIVACY.md)).

### 3. Documents

Manager adds `.txt`/`.md` on the Knowledge screen -> uploaded to the service -> on a search the BM25 index of that
audience (manager: all documents; employee: `visibility = 'everyone'`) is built from the company's documents.

### 4. Live chat and notifications

A message is saved in the database first; after the transaction commits, the service's `ChatHub` pushes it to every
open WebSocket of the conversation's people (the app's `ChatSocket`, the website's browser socket). Unread messages left
for 10 minutes while the person is offline are queued as an e-mail (never with the message text). The hub is in memory:
one service instance (see [PRODUCTION.md](PRODUCTION.md)).

## Extension points (data-driven where possible)

| to add... | change... |
|---|---|
| a chat intent | a phrase bank in `assistant/intents.py`, a `_h_<intent>` method in `assistant/answers.py`, retrain (`python -m assistant.train_intent`) |
| a task "how-to" plan | a playbook entry in `assistant/playbooks.py` |
| a screen category / its badge | `detection/categories.py` + one row in `SCREEN_BADGES` (`ui/employee_screen.py`) |
| a window keyword | `PRODUCTIVE_KEYWORDS` / `DISTRACTION_KEYWORDS` in `detection/screen_monitor.py` |
| a data feature | an Alembic migration (with RLS policy), a service + router in `backend/`, the isolation tests, then the method in `cloud/remote_db.py` and its repository list in `database/repositories.py` |
| a chat backend | subclass `chat.backend_base.ChatBackend`; raise `BackendUnavailable` from `__init__` if it cannot work |
| another language model | the service's AI provider (`backend/app/services/`); the desktop app does not change |

## Composition and injection

`main.App(db=None)` creates the database when none is given. Screens that talk to a service accept it as a constructor
argument and build the default only when nothing was injected:
`AIChatScreen(client=..., model_service=...)`, `KnowledgeScreen(kb=...)`, `ChatClient(backend=...)`.
The shells (`ManagerScreen`, `EmployeeScreen`) still build their own pages; that is the main remaining
"service locator" and is listed in `SOLID_NOTES.md`.
