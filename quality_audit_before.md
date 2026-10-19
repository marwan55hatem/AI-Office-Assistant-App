# Code-quality audit -- BEFORE the refactoring

Scope: every `.py` file (72 files, 19,433 lines): `main.py`, `admin.py`, `ui/`, `admin_ui/`, `database/`, `detection/`,
`assistant/`, `chat/`, `knowledge/`, `llm/` (and the empty `tasks/` package). Tool: `tools/code_audit.py` (standard-library
`ast`/`tokenize` + `pyflakes`); the SOLID review is manual. Line numbers refer to the code *before* the changes.

**Overall health: Good.** The project is feature-complete, consistently formatted (one quote style, LF/CRLF not mixed, no trailing
whitespace, no bare `except:`) and heavily commented. The weak spots are structural: one very large database class, UI
code that talks SQL, a few concrete dependencies built inside screens, duplicated shell code and missing type hints.

## 1.1 SOLID violations (16)

| # | principle | where | what | severity | fix |
|---|---|---|---|---|---|
| 1 | **S** | `database/db_manager.py:154` `DatabaseManager` | one class, 82 methods, 1,338 lines: users, sessions, tasks, calendar, chats, documents, admin, import/export, migrations | 🔴 High | domain repositories on the shared connection |
| 2 | **I** | same class | every caller sees all 82 methods (a chat class can call `delete_user_cascade`) | 🔴 High | narrow repository views, enforced by a test |
| 3 | **S** | `ui/manager_screen.py:573` `_open_session_detail` (107 lines) | loads data, falls back to hand-written SQL, builds a dialog, a label block and a table in one function | 🔴 High | `db.get_session`, split into load / summary / table helpers |
| 4 | **D** | `ui/ai_chat_screen.py:160, 559, 594, 650` | the screen builds its own `ChatClient` and imports `llm.model_manager` / `llm.workers` directly; cannot be tested with a fake | 🔴 High | inject `client` and a `ModelService` |
| 5 | **S** | `admin_ui/add_user_dialog.py:165,175,181,221`, `danger_tab.py:203`, `users_tab.py:254-270`, `ui/manager_screen.py:598` | 12 direct `db.conn` uses (10 queries, 2 commits) run SQL from the UI | 🟡 Medium | named database methods |
| 6 | **L** | `chat/backend_cloud.py:8` | `CloudBackend.__init__` raises `NotImplementedError`; selecting `BACKEND = "cloud"` in config crashed the chat screen; no shared contract between backends | 🟡 Medium | `ChatBackend` ABC, `BackendUnavailable`, fallback to local |
| 7 | **O** | `ui/employee_screen.py:655-691` `_on_screen` | `if/elif` chain over screen categories, every branch repeats two `_set_badge` calls | 🟡 Medium | lookup table `SCREEN_BADGES` |
| 8 | **S** | `main.py:155-171` `_load_todo_tasks` | duplicates what `TodoScreen` already does itself and calls its private `_render_tasks` | 🟡 Medium | removed |
| 9 | **D** | `ui/knowledge_screen.py:52` | builds `KnowledgeBase(db)` internally | 🟡 Medium | `kb=` parameter |
| 10 | **D** | `main.py:56` | `App` creates `DatabaseManager()` itself, so it cannot be given another | 🟡 Medium | `App(db=None)` |
| 11 | **I** | `ui/ai_chat_screen.py` | depends on the whole `LLMManager` but needs five operations | 🟡 Medium | `ModelService` facade |
| 12 | **S** | `ui/employee_screen.py` `SessionPage` (~700 lines) | UI + thread start/stop + DB writes + state change logging | 🟡 Medium | partly: builders split; orchestration documented (see "not changed") |
| 13 | **D** | `ui/manager_screen.py`, `employee_screen.py` | the shells construct all their pages (service-locator style) | 🟡 Medium | not changed (documented) |
| 14 | **O** | `database/db_manager.py` `create_tables` | migrations are a growing run of `if column not in ...` blocks | 🟢 Low | left; documented in DATABASE.md |
| 15 | **L** | `detection/session.py` | legacy attribute `distractions` kept but never incremented | 🟢 Low | left (compatibility, documented) |
| 16 | **D** | `ui/todo_screen.py:18`, `ui/notifications.py:18` | import `format_deadline` / `deadline_state` *via* `ui.calendar_screen` (wrong direction; the real home is Qt-free `assistant/formatting.py`) | 🟢 Low | import from the real module |

Totals: **4 High, 9 Medium, 3 Low.** (Positive example already present: chat intents are dispatched with
`getattr(self, "_h_" + intent)`, so a new intent is a new method, not a new `if`.)

## 1.2 Clean-code issues (measured)

| category | measured | notes |
|---|---|---|
| Function length > 60 lines | **26** (7 over 100) | worst: `chat/selftest.py main` 366, `llm/selftest.py main` 118, `calendar_event_dialog._build_ui` 113, `employee_screen._build_right_column` 108, `signup_screen._build_card` 108, `manager_screen._open_session_detail` 107, `knowledge/selftest.py main` 106 |
| Classes with > 30 methods | 3 | `DatabaseManager` 82, `AIChatScreen` 43, `AssistantEngine` 32 |
| Dead code: unused imports | **16** | + 2 unused variables, a 0-byte `tasks/` package, a stray duplicate `yolo12n.pt` in the project root (left by an earlier test run), the redundant to-do loader in `main.py` |
| Magic numbers (same literal 3+ times in a file) | **48** | e.g. field height `52` (17 times), button height `50` (12 times), card width `520`, `56`, `48` |
| Duplication (identical function bodies across files) | **6 groups** | `_navigate` and `_refresh_calendar_badge` (employee/manager shell), `_clear` (calendar/home), `_card` (settings/knowledge), `refresh_users` (admin tabs), `_back_to_login`/`_after_signup` |
| Duplication (near-identical blocks) | 2 | login and sign-up `_build_card` (95 / 108 lines, same card, brand header, inputs, footer) |
| Comment / docstring quality | **172** public items without a docstring | most are `__init__`, Qt overrides and small properties; stale text in the `main.py` docstring ("camera and AI layers are still not wired ... no background threads") |
| Error handling: bare `except:` | 0 | |
| Error handling: `except Exception: pass`-style silent swallows | **17** | 12 broad (`except Exception`) + 5 narrow control-flow (`ImportError`, `UnicodeDecodeError`, `RuntimeError` ...) |
| Error handling: `print()` instead of logging | **30** error messages (of 34 `print` calls; the other 4 are intentional command-line output) | `print(f"[Manager] ... {error}")` with no traceback |
| Naming | 3 notable | `IDLE_IDLE_TEXT`; magic strings `"productive"`/`"distraction"`/`"idle"` repeated as bare literals in 5 files; two names for one thing (`sample` / `sample_with_timer`) |
| Consistency | clean | quotes: 0 files with a mixed style; line endings: 0 mixed; trailing whitespace: 0 |
| Long lines (> 120) | 142 | 111 of them in the three `selftest.py` scripts, the rest in the phrase banks |
| Type hints on public functions | **320** without any hint (of ~900) | `ui` 100, `database` 78, `assistant` 39, `chat` 29, `llm` 27, `knowledge` 21, `detection` 13 |

Also noted (not code-quality in the strict sense): passwords are stored in plain text (see `docs/PRIVACY.md`); `pytest` was
not installed and there was no automated suite -- only ad-hoc `selftest.py` scripts and `python database/db_manager.py`.

## 1.3 Priority list (impact x frequency / effort)

| rank | item | why it ranks here |
|---|---|---|
| 1 | Replace 30 `print` error messages with `logging` (tracebacks kept) | touches 14 files, trivial, big debuggability win |
| 2 | Remove 16 unused imports / dead code / stray files | trivial, removes noise, makes pyflakes a usable gate |
| 3 | Move the 12 direct `db.conn` uses of the UI into named DB methods | fixes a layering violation, small edits |
| 4 | Narrow repositories alongside `DatabaseManager` (ISP) | fixes the biggest God-class smell without breaking any caller |
| 5 | Replace magic strings with `detection/categories.py` constants | used in 5 files, prevents silent typos |
| 6 | Inject `client` / `model_service` / `kb` / `db` | enables fake-based tests, small edits |
| 7 | De-duplicate shell navigation, card/clear helpers, login/sign-up card | 6 duplicate groups |
| 8 | `ChatBackend` contract + safe `CloudBackend` | removes a reachable crash |
| 9 | `SCREEN_BADGES` table instead of `if/elif` | open/closed example, fewer lines |
| 10 | Name the repeated UI sizes (`FIELD_HEIGHT`, `BUTTON_HEIGHT`) | 48 literals |
| 11 | Split the three > 100-line UI builders | readability |
| 12 | Docstrings on the remaining public API | 172 -> small |
| 13 | Type hints on the non-UI public API | 320 -> fewer |
| 14 | A pytest suite (session timers, classifier, DB, router, privacy, memory) | regression safety for everything above |
| 15 | Architecture / threading / privacy documentation | needed to present the project |
