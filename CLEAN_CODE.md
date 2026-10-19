# Clean-code conventions used in this project

Short rules, each with the reason and how it is checked. `python tools/code_audit.py` prints the numbers.

## Layout and naming
* **Python 3.12, PEP 8 spacing, double quotes, 4-space indent, LF/CRLF never mixed.** (Audit: 0 files with mixed quotes or line endings, 0 lines with trailing whitespace.)
* **Names say what a thing is.** `INPUT_IDLE_TEXT` (was `IDLE_IDLE_TEXT`), `SCREEN_BADGES`, `count_user_related_rows`.
  Qt widgets keep a type suffix only where it avoids a clash (`session_button`, `error_label`); old short aliases (`..._lbl`) remain for
  existing callers and are documented as aliases.
* **Constants are UPPER_CASE and named for their meaning, not their value.** `FIELD_HEIGHT = 52`, `SUBMIT_BUTTON_HEIGHT = 56`,
  `AUTH_CARD_WIDTH = 520`, `EVENT_ROW_HEIGHT = 48`. A literal that appears three or more times in a file becomes a constant.
* **Strings that act as an enum get a module of constants.** `detection/categories.py` (`SCREEN_*`, `FOCUS/DISTRACTION/AWAY`) -- no bare
  `"distraction"` in logic.
* **Private = leading underscore.** Public API of a module is what the docstring and `tests/` use.

## Functions
* **One job, about 60 lines at most.** UI builders are split into `_add_<section>(layout)` methods; the remaining long ones are mostly
  linear widget construction and the three `selftest.py` report scripts (listed in `quality_audit_after.md`).
* **Early return over nesting.** Guard clauses (`if self.db is None: return`) first.
* **No hidden I/O in "get" methods of pure modules.** `assistant/`, `knowledge/`, `chat/`, `detection/session.py` are Qt-free and testable.

## Comments and docstrings
* **Every module, class and public function has a docstring** that says *what and why*, not how (`__init__` is described by the class docstring).
* **Comments explain a reason, a trade-off or a trap** ("a word-wrapped QLabel otherwise picks a narrow default width"), never restate the line.
* **Stale text is a bug.** (`main.py`'s module docstring was rewritten to match the code.)
* The generated documents (`docs/DATABASE.md`) come from the code so they cannot go stale.

## Errors and logging
* **Never `except:`; never silence `except Exception`.** Broad catches log through `logging` with the traceback
  (`logger.warning("...", exc_info=True)`); narrow catches (`ImportError`, `UnicodeDecodeError`) are control flow and stay silent.
* **`print` is for command-line tools only.** The app configures logging once in `main.configure_logging()`.
* **Messages for the user are friendly; details go to the log.** (`QMessageBox` text vs `logger.warning`.)
* **A worker never raises into the GUI thread**: it emits `failed(message)` (see `docs/THREADING.md`).

## Structure
* **Layering:** UI -> services (`chat`, `knowledge`, `llm`, `detection`) -> `database`. Only `database/` contains SQL.
* **Shared helpers live once:** `ui/widgets.py` (`make_card`, `clear_layout`), `ui/shell.py`, `ui/auth_form.py`.
* **Dependencies are passed in** (`client=`, `model_service=`, `kb=`, `db=`), defaults are built only when nothing is given.
* **Heavy imports are lazy** (`torch`, `transformers`, `ultralytics`): start-up stays fast and tests do not need them.
* **Data over code:** tables for badges, repositories, phrase banks, playbooks and keyword lists.

## Types
* **Public APIs of the non-UI packages carry type hints** (`database`, `chat`, `knowledge`, `llm`, parts of `detection`/`assistant`).
  Qt widget methods are mostly untyped (their signature is dictated by Qt and the value of hints is low).

## Tests
* **pytest, no real data:** every test builds a temporary database (`tests/conftest.py`); no test reads `data/`.
* **Names are sentences** (`test_an_employee_gets_a_refusal_with_no_names_or_numbers`) so a failure reads like a requirement.
* **Fakes at the seams** (`FakeModelService`, a controllable clock for the WhatsApp rule), not mocks of internals.
* **Privacy rules have their own tests** (`tests/test_privacy.py`).

## Before you commit
```bash
python -m pyflakes main.py admin.py ui admin_ui database detection assistant chat knowledge llm tools tests
#   (the 3 'sentencepiece imported but unused' lines are deliberate: it must be imported before PyQt5 on Windows)
python -m pytest tests/
python database/db_manager.py          # "All DatabaseManager tests passed"
python tools/code_audit.py             # compare with quality_audit_after.md
```
