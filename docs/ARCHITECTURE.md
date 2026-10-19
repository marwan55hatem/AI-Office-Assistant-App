# Architecture

A fully local Windows desktop application: **Python 3.12, PyQt5, SQLite**. Nothing is sent to a server.

## Layers

```
                    main.py  (composition root)         admin.py (standalone admin panel)
                       |                                        |
        +--------------+---------------+                        |
        v                              v                        v
   ui/  (screens, widgets, theme)                         admin_ui/
        |        \
        |         +--> chat/  ----> assistant/ (intent engine)      detection/ (camera, screen, session timers)
        |                  \------> knowledge/ (BM25 search)               |
        |                   \-----> llm/ (language model)                  |
        v                                                                  |
   database/  <-----------------------------------------------------------+   (only main-thread code touches it)
```

Rules of dependency (checked by the tests where possible):

* `ui/` and `admin_ui/` depend on `database/`, `chat/`, `detection/` -- never the other way round.
* `assistant/`, `chat/`, `knowledge/`, `detection/session.py`, `detection/categories.py` are **Qt-free**; they can be
  tested without a display (`tests/`).
* Only `database/` writes SQL. The UI calls named methods (`db.get_session(...)`), never `db.conn`.
* Heavy libraries (`torch`, `transformers`, `ultralytics`) are imported lazily, so the window opens fast.

## Module map

| package | files | responsibility |
|---|---|---|
| `main.py` | `App` | **composition root**: creates the `DatabaseManager`, builds the screens, navigation, tray notifier, logging |
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
| `chat/` | `chat_client`, `backend_base`, `backend_local`, `backend_cloud`, `models`, `config` | the contract + the local implementation; routing between engine / model / documents |
| `llm/` | `model_manager`, `service`, `workers`, `prompts`, `status`, `config` | Qwen2.5-1.5B: loading, streaming, prompts, status, the UI-facing service |
| `knowledge/` | `text`, `bm25`, `store` | chunking, BM25 ranking, documents + visibility |
| `database/` | `db_manager`, `repositories` | SQLite schema, migrations, all queries; narrow repository views |
| `admin_ui/` | window + tabs | users, sessions, tasks, events, danger zone |
| `tools/` | `code_audit`, `generate_database_docs` | maintenance scripts |
| `tests/` | 11 test files + `conftest.py` | the pytest suite (167 tests) |

## Data flows

### 1. A work session

```
CameraThread --detection_update(person, phone)--+
ScreenThread --screen_update(title, category)---+--> EmployeeScreen --> SessionState (3 timers)
ScreenThread --idle_update(is_idle, seconds)----+          ^
QTimer (1 s) ---------------------------------------- tick()  -> one second to exactly one of focus / distraction / away
                                                       |
                                       state changes -> db.log_event(...)      (events table)
                                       stop          -> db.end_session(...)    (totals, screen counters)
```

`SessionState` priority (first match wins): keyboard idle -> away; nobody in frame -> away; phone -> distraction;
distracting window -> distraction; idle window -> away; otherwise focus.

### 2. A chat question

```
AIChatScreen --> ChatClient --> LocalBackend.stream_reply
                                   |  1. AssistantEngine.ask(text)       (intent + the user's own data, from SQL)
                                   |  2. KnowledgeBase.search(text, role) (only when the engine is not sure)
                                   |  3. route:
                                   |       data question         -> engine text            -> typed into the bubble
                                   |       general / document    -> prompt for the model   -> GenerateWorker (thread)
                                   |       model off / missing   -> engine text, or the quoted passages
                                   v
                 ReplyStream (kind "text" | "llm", source "engine" | "llm", sources [...])
```

The model's prompt is built from a fixed instruction, its **own** earlier answers in this chat (messages stored with
`source = 'llm'`) and the matching document passages. It never receives database content (see [PRIVACY.md](PRIVACY.md)).

### 3. Documents

Manager adds `.txt`/`.md` on the Knowledge screen -> `KnowledgeBase.add_file` -> `knowledge_docs` row ->
on the next search the BM25 index of that audience (manager: all documents; employee: `visibility = 'everyone'`) is rebuilt
when the table signature changed.

## Extension points (data-driven where possible)

| to add... | change... |
|---|---|
| a chat intent | a phrase bank in `assistant/intents.py`, a `_h_<intent>` method in `assistant/answers.py`, retrain (`python -m assistant.train_intent`) |
| a task "how-to" plan | a playbook entry in `assistant/playbooks.py` |
| a screen category / its badge | `detection/categories.py` + one row in `SCREEN_BADGES` (`ui/employee_screen.py`) |
| a window keyword | `PRODUCTIVE_KEYWORDS` / `DISTRACTION_KEYWORDS` in `detection/screen_monitor.py` |
| a database method | the method in `DatabaseManager` **and** its repository list in `database/repositories.py` (a test enforces this) |
| a chat backend | subclass `chat.backend_base.ChatBackend`; raise `BackendUnavailable` from `__init__` if it cannot work |
| another language model | an object with the `ModelService` methods (`llm/service.py`), injected into `AIChatScreen(model_service=...)` |

## Composition and injection

`main.App(db=None)` creates the database when none is given. Screens that talk to a service accept it as a constructor
argument and build the default only when nothing was injected:
`AIChatScreen(client=..., model_service=...)`, `KnowledgeScreen(kb=...)`, `ChatClient(backend=...)`.
The shells (`ManagerScreen`, `EmployeeScreen`) still build their own pages; that is the main remaining
"service locator" and is listed in `SOLID_NOTES.md`.
