# Testing

## Automated

| command | what it checks | needs |
|---|---|---|
| `python -m pytest tests/` | 167 tests: session timers and their priority rules, window classification and the WhatsApp rule, database (accounts, tasks, deadlines, calendar, sessions, migrations, export/import), chat routing (engine vs model), privacy (employees never get team data; the model prompt never contains database content), chat memory, BM25 knowledge search, safe Markdown, repositories and the backend contract, headless screens (login, sign-up, chat with a fake model, settings, knowledge, admin dialogs) | nothing — temporary databases, offscreen Qt, fake model |
| `python database/db_manager.py` | the database self-test (all methods on a copy) | — |
| `python -m chat.selftest` | 112 checks of the chat engine with readable output | — |
| `python -m knowledge.selftest` | 42 checks of chunking, BM25 and visibility | — |
| `python main.py --self-check` (or `OfficeAssistant.exe --self-check`) | loads and runs every shipped model once (detector, summariser, translator, chat) + database; exit code = failures; results in the log | the model files |
| `python -m llm.selftest` | the real Qwen model: load, stream, stop, history trimming, CPU fallback, Qt workers | the model files; a GPU for speed |

All of them must pass before a release (the build script runs pytest and the database self-test automatically).

## Manual acceptance checklist (on the installed app)

1. Log in as `manager` and as `marwan`; sign up a new employee and approve it.
2. Employee: **Start session** — the camera preview shows, *Person* turns green; switch to a distracting site —
   the distraction timer runs; leave the keyboard for 90 s — away runs; **Stop session** — the session appears
   under the manager's *Sessions*.
3. Manager assigns a task with a deadline in 1 hour — the employee sees it with a *due soon* badge and gets a notification.
4. Manager creates a calendar event inviting the employee — it appears in the employee's calendar and badge.
5. AI Helper: summarise a paragraph, open a PDF and summarise it, translate English → Arabic and Arabic → French.
6. AI Chat (employee): "What tasks do I have?" (engine), "How do I build a CNN?" (model, streams; *Stop* works),
   "Who is the best performer?" (refused).
7. Manager: add a `.md` note under *Knowledge*; ask the chat about it — the answer ends with *Sources: <file>*.
8. Settings: switch the theme; switch the AI model off — the chat badge says *off*.
9. Admin panel: export the database, then import it back.
10. With the network disconnected, repeat 5 and 6 — everything still works (models are bundled).
