# Testing

## Automated

| command | what it checks | needs |
|---|---|---|
| `python -m pytest tests/` | desktop app: session timers and their priority rules, window classification, the client for the online service (offline outbox, token refresh, live chat socket), chat routing (classifier vs online model), privacy (employees never get team data; the online model never receives tasks, calendars or team numbers), BM25 knowledge search, safe Markdown, repositories, headless screens (sign-in, sign-up, chat, settings, knowledge, reports, meetings, messages) | nothing — offscreen Qt, fake service and fake model |
| `cd backend && python -m pytest` | online service: accounts, invites, approval, tokens and rotation, password reset, rate limits, sessions, reports, tasks, calendar, meeting requests, chat (REST + WebSocket), e-mail queue and templates, AI Chat, **tenant isolation of every table and endpoint (application filter and Row-Level Security)**, production settings | PostgreSQL 17 in Docker (`docker compose up -d db`) |
| `cd website && npm run lint && npm run typecheck && npm test` | website: lint, types, unit tests (forms, validation, dictionaries, proxy rules) | Node 22 |
| `cd website && npx playwright test` | website end to end in Chromium: pages in both languages and themes, sign-up / sign-in / reset, portal, accessibility (axe) | the service and the website running |
| `python -m chat.selftest` | the chat engine with readable output | — |
| `python -m knowledge.selftest` | chunking, BM25 and visibility | — |
| `python self_check.py` (or `OfficeAssistant.exe --self-check`) | loads and runs every local model once (intent classifier, detector, summariser, translator) and the local data folder; exit code = failures | the model files |
| `SOURCE_URL=… RESTORED_URL=… python backend/scripts/restore_check.py` | a restored backup has every table with the same rows | two databases |

CI (`.github/workflows/ci.yml`) runs the service and website suites on every push. The installer build
script runs the desktop tests and the frozen self-check.

## Manual acceptance checklist (installed app + website)

1. Website: create a company; copy the company code. App: *Join a company* as an employee; the manager
   approves them on the website or in the app.
2. Employee: **Start session** — the camera preview shows, *Person* turns green; switch to a distracting site —
   the distraction timer runs; leave the keyboard for 90 s — away runs; **Stop session** — the session appears
   in the manager's *Reports*.
3. Disconnect the network during a session, stop it, reconnect — the session is sent (offline banner, then gone).
4. Manager assigns an **urgent** task — the employee sees it and receives an e-mail.
5. Employee requests a meeting with 2 times; the manager proposes another; the employee accepts — it is in
   both calendars.
6. Messages: employee writes, manager answers on the website — both see it live, with *Read* ticks.
7. AI Helper: summarise a paragraph and a PDF, translate English → Arabic and Arabic → French.
8. AI Chat (employee): "What tasks do I have?" (from your data), "How do I build a CNN?" (online model),
   "Who is the best performer?" (refused).
9. Manager: add a `.md` note under *Knowledge*; ask the chat about it — the answer ends with *Sources: <file>*.
10. Website: forgot password → e-mail link → new password → sign in; switch language and theme.
