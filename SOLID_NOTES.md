# SOLID in this project

Each principle: the idea in one sentence, a **before/after from this code base**, where to look, and what is *still* open.
Everything referenced is covered by a test (`python -m pytest tests/`).

---

## S -- Single Responsibility: a class has one reason to change

**Before.** `ui/manager_screen.py::_open_session_detail` (107 lines) loaded data, fell back to hand-written SQL when the first
query missed, then built a dialog, a text block and a table. A change to the SQL, the wording or the table layout all meant
editing the same function.

**After.**
```python
def _open_session_detail(self, session_id):        # builds the dialog frame only
    session, events = self._load_session_detail(session_id)       # data (and the error box)
    layout.addWidget(self._session_summary_label(session))        # the numbers
    layout.addWidget(self._build_events_table(events), 1)         # the event log
```
and the SQL lives in `DatabaseManager.get_session`. Same pattern: `ui/auth_form.py` (the card, brand header, input, error
label shared by login and sign-up), `ui/shell.py` (navigation + calendar badge shared by the two shells),
`employee_screen._build_right_column` (five section methods), `calendar_event_dialog._build_ui` (five).

**Also:** twelve direct `db.conn` uses (10 queries, 2 commits) in the admin panel and the session dialog became `username_taken`, `create_user`,
`count_user_related_rows`, `delete_all_tasks`: *a screen does not know SQL*.

**Still open.** `SessionPage` (employee) both builds the screen and orchestrates threads and DB writes; `DatabaseManager`
still *implements* ~87 methods (it now *exposes* them through repositories -- see I).

---

## O -- Open/Closed: extend by adding data, not by editing `if` chains

**Before.** `employee_screen._on_screen` chose a badge with an `if/elif` ladder and repeated two `_set_badge` calls in every branch.

**After.**
```python
SCREEN_BADGES = {
    SCREEN_PRODUCTIVE:  ("🟢  Screen: Productive", "SUCCESS"),
    SCREEN_DISTRACTION: ("🟡  Screen: Distracted", "WARNING"),
    SCREEN_IDLE:        (SCREEN_IDLE_TEXT,         "TEXT_MUTED"),
    SCREEN_NEUTRAL:     ("⚪  Screen: Neutral",    "TEXT_MUTED"),
}
text, colour_name = SCREEN_BADGES.get(category, SCREEN_BADGES[SCREEN_NEUTRAL])
```
A new category is one new row. (The colour is stored *by name* so a theme switch is honoured.)

**Already good, kept.** The chat engine dispatches with `getattr(self, "_h_" + intent)`: a new intent is a new method plus
phrases in `assistant/intents.py` -- no existing code changes. Playbooks (`assistant/playbooks.py`), keyword lists
(`PRODUCTIVE_KEYWORDS`...) and the `REPOSITORIES` table work the same way.

**Still open.** Schema migrations in `create_tables` are a sequence of `if column not in ...` blocks.

---

## L -- Liskov Substitution: any implementation can replace the interface

**Before.** `CloudBackend.__init__` raised `NotImplementedError`, and `ChatClient` built it whenever the config said
`BACKEND = "cloud"` -- so "swapping the backend" crashed the app, and nothing said what a backend must provide.

**After.** `chat/backend_base.py` defines the contract (`ChatBackend`, nine abstract methods) and a single failure mode:
```python
class BackendUnavailable(RuntimeError): ...
# a backend either implements everything or refuses to be created:
class CloudBackend(ChatBackend):
    def __init__(self, base_url): raise BackendUnavailable("... not implemented yet ...")
# the client treats every backend alike and degrades gracefully:
except BackendUnavailable as problem:
    logger.warning("%s Using the local assistant instead.", problem)
```
`tests/test_repositories.py` checks the contract is complete, that `LocalBackend` keeps it, and that choosing "cloud" falls back to local.

**Also.** Every screen method called `refresh()` has the same meaning (reload from the database; safe to call repeatedly) so the shells
can call it blindly (`ShellNavigationMixin._navigate`).

**Still open.** `SessionState.distractions` is a legacy attribute that exists but is never incremented (kept for old callers).

---

## I -- Interface Segregation: depend only on what you use

**Before.** One `DatabaseManager` with 82 public methods. `LocalBackend` needed 9 of them and could call all 82.

**After.** `database/repositories.py`: `db.users`, `db.sessions`, `db.activity`, `db.tasks`, `db.calendar`, `db.chats`, `db.knowledge`,
`db.admin`. Each exposes **only** its own methods (anything else raises `AttributeError`), on the same connection. The old API
still works, so no caller broke. `LocalBackend` now uses `db.chats` + `db.users`, `KnowledgeBase` uses `db.knowledge`, and
`tests/test_repositories.py` fails if a method is added to `DatabaseManager` without being assigned to a repository.

Same idea for the model: `AIChatScreen` needs five things from the language model, so it depends on the five-method
`llm.service.ModelService`, not on `LLMManager` + two worker classes.

**Still open.** Most older code (`manager_screen`, `employee_screen`, the engine) still calls the flat `db.*` API; migrating them is
mechanical and can be done one class at a time.

---

## D -- Dependency Inversion: depend on abstractions, receive them from outside

**Before.** `AIChatScreen.__init__` did `ChatClient(db, ...)` and imported `llm.model_manager` / `llm.workers` inside its methods;
`KnowledgeScreen` did `KnowledgeBase(db)`; `App` did `DatabaseManager()`. None could be tested with a stand-in.

**After.**
```python
AIChatScreen(user, db, client=None, model_service=None)    # defaults are built only when nothing is injected
KnowledgeScreen(user, db, kb=None)
App(parent=None, db=None)
ChatClient(db, user_id, backend=None)
```
`tests/test_ui_smoke.py::test_the_chat_screen_runs_on_an_injected_model_service` drives the real chat screen with a
`FakeModelService` and a fake worker -- no GPU, no 3 GB model -- and checks the whole path (route, stream, format, store).

Also fixed: `todo_screen` and `notifications` imported `format_deadline` *through* a UI module; they now import it from the Qt-free
`assistant/formatting.py` (UI depends on the domain helper, not the other way round).

**Still open.** `ManagerScreen` / `EmployeeScreen` construct their own page objects (a service-locator shape). Making them accept
a page factory is the next step; it was left because the pages are only ever used inside these two shells.

---

### Summary table

| principle | applied | evidence |
|---|---|---|
| S | session-detail dialog, auth forms, shell mixin, DB access out of the UI | `ui/auth_form.py`, `ui/shell.py`, `db.get_session` ... |
| O | `SCREEN_BADGES`, `REPOSITORIES`, existing intent dispatch | `ui/employee_screen.py`, `database/repositories.py` |
| L | `ChatBackend` + `BackendUnavailable` + fallback | `chat/backend_base.py`, `tests/test_repositories.py` |
| I | repositories, `ModelService` | `database/repositories.py`, `llm/service.py` |
| D | constructor injection of `db`, `client`, `model_service`, `kb`, `backend` | `tests/test_ui_smoke.py` |
