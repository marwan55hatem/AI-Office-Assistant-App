# Code-quality audit -- AFTER the refactoring

Same tool (`python tools/code_audit.py`), same rules as `quality_audit_before.md`. All numbers below were measured, not estimated.
Every existing feature still works: see "Verification" at the end.

## Result at a glance

| metric | before | after | change |
|---|---|---|---|
| Python files / lines (excluding tests and tools) | 72 / 19,433 | 78 incl. 7 new modules / 19,882 | +7 modules (one removed) |
| SOLID violations found (manual review) | 16 (4 high, 9 medium, 3 low) | **5 open** (0 high, 3 medium, 2 low) -- 11 fixed, see below | -11 |
| Unused imports (pyflakes) | 16 | **0** | fixed |
| Other pyflakes warnings (unused variables) | 2 | **0** | fixed |
| Silently swallowed `except Exception` | 12 broad (+5 narrow, legitimate) | **0** broad | all log with traceback |
| `print()` used for errors | 30 | **0** (4 deliberate command-line prints remain) | `logging` |
| SQL outside `database/` | 12 direct `db.conn` uses | **0** | named DB methods |
| Functions > 60 lines | 26 | **21** | -5 |
| Functions > 100 lines | 7 | **3** (all `selftest.py` report scripts) | -4 |
| Classes with > 30 methods | 3 | **4** | +1: `SessionPage` went from 27 to 31 methods because its builder was split into helpers (`DatabaseManager`, `AIChatScreen`, `AssistantEngine` unchanged) |
| Duplicated function bodies across files | 6 groups (+2 near-identical blocks) | **1** (`refresh_users` in two admin tabs) | -5 |
| Public items without docstring | 172 (74 when `__init__`, Qt overrides and nested helpers are excluded -- the rule used from here on) | **10** (all in the legacy `selftest.py` scripts) | 74 -> 10 on the same rule |
| Public functions without type hints | 320 | **219** (non-UI packages: 209 -> 100; UI: 111 -> 119, because the new UI helper modules are not annotated) | -101 |
| Magic numbers (same literal 3+ times / file) | 48 | **38** (the named ones were the 29 repeated heights) | -10 |
| Mixed quotes / line endings / trailing whitespace | 0 / 0 / 0 | 0 / 0 / 0 | unchanged (clean) |
| Automated tests | 0 pytest (ad-hoc `selftest.py` scripts) | **167 pytest tests** + the older scripts | +167 |
| Dev dependencies | none declared | `requirements-dev.txt` (pytest, pyflakes); **`requirements.txt` unchanged** | new file |
| Documentation | comments only | `docs/` (6 files) + 4 reports + generated DB reference | new |

**Overall code health: Good -> Very good.** The structural risks (God class, SQL in the UI, concrete dependencies, a reachable crash) are
gone; what remains is long Qt layout code, UI type hints and a few structural choices listed under "not changed".

## The fixes, in priority order

| rank | item (before report) | done | how |
|---|---|---|---|
| 1 | `print` errors -> `logging` | yes | 30 messages converted (`logger.warning(..., exc_info=True)`); `main.configure_logging()` |
| 2 | dead code / unused imports | yes | 16 imports, 2 variables, `tasks/` (0 bytes), stray `yolo12n.pt` copy, redundant `_load_todo_tasks` |
| 3 | SQL out of the UI | yes | `get_session`, `username_taken`, `create_user`, `count_user_related_rows`, `delete_all_tasks` |
| 4 | repositories (ISP) | yes | `database/repositories.py` (8 repositories); old API unchanged; coverage test |
| 5 | category constants | yes | `detection/categories.py`, used by `session`, `screen_monitor`, `employee_screen` |
| 6 | dependency injection | yes | `App(db)`, `AIChatScreen(client, model_service)`, `KnowledgeScreen(kb)`, `ChatClient(backend)`; `llm/service.py` |
| 7 | de-duplication | yes | `ui/shell.py`, `ui/widgets.py`, `ui/auth_form.py` |
| 8 | `ChatBackend` contract | yes | `chat/backend_base.py`, safe `CloudBackend`, client fallback |
| 9 | `SCREEN_BADGES` | yes | `employee_screen._on_screen` is 8 lines instead of 40 |
| 10 | named UI sizes | partly | `theme.FIELD_HEIGHT`, `theme.BUTTON_HEIGHT` (29 literals), `auth_form` constants, event-log constants |
| 11 | split long builders | partly | `_open_session_detail`, login/sign-up cards, `_build_right_column`, calendar dialog `_build_ui` split; others remain |
| 12 | docstrings | yes | 65 added by script review + the new modules; the 10 left are in `selftest.py` helper functions |
| 13 | type hints | partly | database (78 -> 17 missing), chat, knowledge, llm, detection, answers; UI widgets not annotated |
| 14 | pytest suite | yes | 167 tests in 11 files, no `data/` file needed |
| 15 | documentation | yes | `docs/` + `SOLID_NOTES.md` + `CLEAN_CODE.md` + these audits |

### Bugs found and fixed on the way
* **Retrieval:** in a *one-document* knowledge base, "How many days for travel claims?" returned nothing, because the unmatched filler
  word "many" outweighed the matched words. Fixed (`many/much/long/often` are question filler; a matched word has a minimum weight).
  Found by the new `tests/test_knowledge.py`.
* **A crash path:** choosing `BACKEND = "cloud"` in `chat/config.py` raised `NotImplementedError` while building the chat screen. It now
  logs a warning and uses the local backend.
* **Stale documentation in code:** `main.py`'s module docstring claimed there were no background threads and that the camera/AI layers were
  not wired.
* **Introduced and caught during this task:** a displaced module docstring in `admin_ui/users_tab.py` (found by the audit tool, fixed).

## Renames, moves and removed items (every caller updated)

| old | new | callers |
|---|---|---|
| `IDLE_IDLE_TEXT` (`ui/employee_screen.py`) | `INPUT_IDLE_TEXT` | 3 uses in the same file |
| `App._back_to_login`, `App._after_signup`, `App._new_login_screen` (`main.py`, private) | `App._show_fresh_login` | the two signal connections in `_open_signup` |
| `App._load_todo_tasks` (`main.py`, private) | removed (`TodoScreen` loads its own rows) | `_open_todo` |
| `from ui.calendar_screen import format_deadline, deadline_state` | `from assistant.formatting import ...` (the real home; `ui.calendar_screen` no longer re-exports `SOON_HOURS`, `deadline_state`, `deadline_due_datetime`) | `ui/todo_screen.py`, `ui/notifications.py`, `ui/manager_screen.py`, the old test drivers |
| `SettingsScreen._card`, `KnowledgeScreen._card` | `ui.widgets.make_card` | both screens |
| `CalendarScreen._clear`, `ManagerHomeScreen._clear` | `ui.widgets.clear_layout` | both screens |
| `EmployeeScreen/ManagerScreen._navigate`, `_refresh_calendar_badge` | `ShellNavigationMixin` (`ui/shell.py`), same names | unchanged call sites |
| `FOCUS/DISTRACTION/AWAY` defined in `detection/session.py` | defined in `detection/categories.py`, **re-exported** from `detection.session` | `from detection.session import FOCUS` still works |
| `ChatClient`: `from chat.config import BACKEND` | reads `chat.config.BACKEND` at call time | nothing else |
| `empty package tasks/` | removed (0 bytes, nothing imported it) | none |

New modules: `chat/backend_base.py`, `database/repositories.py`, `detection/categories.py`, `llm/service.py`, `ui/auth_form.py`,
`ui/shell.py`, `ui/widgets.py` -- and `tools/`, `tests/`, `docs/`.

New public database methods: `get_session`, `username_taken`, `create_user`, `count_user_related_rows`, `delete_all_tasks`; new `DatabaseManager`
attributes `users`, `sessions`, `activity`, `tasks`, `calendar`, `chats`, `knowledge`, `admin` (the repositories). **No schema change.**

### Behaviour that is intentionally different (documented, small)
* Error messages previously printed as `[Manager] status reload failed: ...` now appear as `WARNING [ui.manager_screen] ...` followed by the traceback.
* The knowledge search weighting (above) can now return a passage in the cases that used to return nothing.
* Selecting the cloud chat backend no longer crashes.

## Not changed on purpose

| item | why it was left |
|---|---|
| **Plain-text passwords** (`users.password`) | hashing would remove a visible feature (the admin panel reads/resets the stored value) and break the database self-test; needs a migration plan -- described in `docs/PRIVACY.md` |
| `ManagerScreen` / `EmployeeScreen` build their own pages | making them accept page factories is a larger change with little payoff while the pages are only used there; listed under D in `SOLID_NOTES.md` |
| `SessionPage` (employee) orchestrates threads + DB + UI | splitting it is a real redesign of the session start/stop sequence, which is the most hardware-dependent code; the builders were split, the orchestration left (31 methods) |
| `ui/manager_screen.py` (5 page classes, ~1,350 lines) in one file | moving classes to separate modules would change import paths used by tests and drivers; the file is organised by `class`, each with one purpose |
| 18 other functions of 60-99 lines (mostly Qt layout code) | linear widget construction; splitting further would obscure the layout without reducing risk |
| `theme.py` (1,800 lines) | it is data (the QSS design system), not logic |
| Flat `db.*` calls in older code | the repositories are additive; migrating `manager_screen`/`employee_screen`/the engine is mechanical and can be done class by class |
| UI type hints (219 remain) | signatures are dictated by Qt; low value |
| The 38 remaining repeated numbers | layout paddings and spacings inside one screen (`3`, `4`, `5`, `8`); naming each would add noise |
| `create_tables()` migration chain, `SessionState.distractions` legacy attribute, `ScreenMonitor.sample()` wrapper | backward compatibility; documented |
| Three `selftest.py` scripts with 100+ line `main()` | report-printing scripts superseded by `tests/`; kept because `llm/selftest.py` is the only check that loads the real model |
| `DEMO_MODE` flag in `main.py` | a developer switch for a database-less demo; documented, unused by default |

## Verification (all run on the final code)

| check | result |
|---|---|
| `python database/db_manager.py` | **All DatabaseManager tests passed** |
| `python main.py` (real launch, 8 s) | stays up, no output, no errors |
| `python -m pytest tests/` | **167 passed** |
| `python -m pyflakes` over the whole project | clean (only the 3 deliberate `sentencepiece` pre-imports) |
| UI regression drivers (login/manager/employee/settings, 1280 x 800 and 1100 x 700) | 25/25 + 25/25 |
| Descriptions / deadlines / calendar / notifications | 15 / 25 / 38 / 29 passed |
| Chat UI (engine) | 33/33 and 38/38 |
| Chat + model UI with the real Qwen model (streaming, Stop, privacy, restart) | 36/36 |
| Documents (RAG) UI with the real model | 36/36 |
| Markdown, code blocks, badge, Settings switch | 46/46 |
| `llm/selftest.py` (load, stream, stop, CPU fallback, workers) | 21/21 |
| `chat/selftest.py`, `knowledge/selftest.py` | 112/112, 42/42 |
| **Real session**: camera + YOLO detects a person, screen classified, timers count, session saved; AI Helper **summarize** and **translate** (Arabic) | 7/7, Qt warnings: none |
| Window minimum size | 1186 x 682 (still under the 700 px target height) |
| Qt warnings in every driver | none |
