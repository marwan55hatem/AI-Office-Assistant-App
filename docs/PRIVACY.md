# Privacy

The product monitors people, so privacy is a design requirement, not an afterthought. This page says what is
collected, what is deliberately **not**, who can see what, and where the guarantees are enforced (and tested).

## 1. What is collected during a session

| signal | how | what is kept |
|---|---|---|
| presence / phone | webcam frame -> YOLO12n | **two booleans per frame** feed the timers. The frame is shown in the employee's own preview and dropped. **No image or video is ever written to disk** (no `imwrite`/`VideoWriter` anywhere in the code). |
| focused window | the window **title** only (`SendMessageTimeoutW`) | classified as productive / neutral / distraction / idle; the title is shown on the employee's own screen and held in memory. **It is not stored in the database.** |
| keyboard / mouse | Win32 `GetLastInputInfo` -> "seconds since last input" | one number. **No key is read or logged, no mouse position, no screenshot.** |
| result | three time counters + three screen counters | `sessions` row; `events` rows hold only the *type* (`focus` / `distraction` / `away`) and a timestamp |

## 2. Who can see what

| data | employee | manager |
|---|---|---|
| own sessions, tasks, calendar, chats | yes | yes (own) |
| other employees' sessions and numbers | **no** | yes (Employees, Sessions, Reports, Home) |
| team questions in the AI Chat | **refused** | answered from SQL |
| documents marked *Everyone* | searchable | searchable |
| documents marked *Managers only* | **invisible** | searchable |
| another user's chat | **no** (`PermissionError`) | no (chats are private to their owner) |

## 3. How the AI Chat enforces it (by construction, not by a prompt)

1. **Role gate before data.** `AssistantEngine.ask` loads other people's records only when the asker is a manager
   (`people = self._employees() if is_manager else []`). A manager-only intent asked by an employee returns a refusal *before*
   any team query runs. `tests/test_privacy.py` makes the employee's `_employees()` raise and asks every team question.
2. **The language model never sees the database.** Its prompt is a fixed instruction, its own earlier answers, the question and
   document passages. Task titles, names and team numbers are not in it; `test_the_model_prompt_never_contains_database_content`
   asserts this for an employee, a manager and a one-task user.
3. **The model's memory contains only its own answers.** Every stored assistant message has a `source` (`engine` or `llm`).
   Only `llm` pairs are fed back, so a data-bearing engine reply (a task list, the team status) can never re-enter a prompt.
4. **Visibility is applied before search.** An employee's BM25 index is *built* from the `everyone` documents only; a manager-only
   passage cannot be ranked, quoted, put in a prompt or cited for an employee. Changing a document's visibility takes
   effect at once (the index is rebuilt when the table signature changes).
5. **Ownership checks.** Every chat operation first checks `chat.user_id == the logged-in user`.
6. **Interface segregation helps.** `db.chats` / `db.knowledge` repositories expose only their own methods, so code that handles
   chats cannot call, say, `delete_user_cascade` (tested).

## 4. Where data goes

* **Nothing leaves the computer** while the app works: no telemetry, no cloud API, no analytics.
* The language model loads with `local_files_only=True`.
* The first use of the *summariser* and the *translator* downloads their model weights from the Hugging Face hub if they are
  not already in the local cache (one-time, no user data is sent). After that they run offline.

## 5. Known limitations (honest list)

| limitation | consequence | suggested next step |
|---|---|---|
| **Passwords are stored in plain text** in `users.password` | anyone who can open `data/office_assistant.db` can read them; `get_all_users` returns them to the admin panel, which can also reset them | salted PBKDF2/bcrypt hash with a login-time upgrade of old rows (**not done**: the admin panel and the database self-test rely on the stored value) |
| The database file is not encrypted | file access = data access | OS-level disk encryption, or SQLCipher |
| Roles are enforced by the application, not by the database | a modified client could bypass them | acceptable for a local single-user-per-PC tool; a server would need server-side checks |
| Demo accounts (`manager/1234`, `marwan/1234`) are re-created by `seed_demo_users` / `factory_reset` | known credentials on a fresh install | force a password change on first login |
| The intent classifier is ~85 % accurate | a wrong intent gives a wrong *kind* of answer, never a leak: for an employee a team intent is refused, or -- when it was only a weak match -- the question goes to the model, which has no data at all | more training data |
| The 1.5 B model can be wrong | an answer may be inaccurate | the UI labels sources; read generated code before using it |
