# Changelog

## 2.0.0 — 2026-11

Online and multi-company. Built phase by phase on the `cloud-upgrade` branch; details in
[docs/CHANGELOG-cloud.md](docs/CHANGELOG-cloud.md).

### Added
- Online service (`backend/`): FastAPI + PostgreSQL 17 with Alembic; companies, company codes, invite links,
  approval; Argon2id passwords, 15-minute access tokens and rotating refresh tokens; password reset by e-mail.
- Tenant isolation twice: every query filtered by company and PostgreSQL Row-Level Security (forced, an API
  role that cannot bypass it); isolation tests for every table and endpoint.
- Reports from the server: focus / distraction / away, hours, attendance, trends, ranking, most-used apps,
  drill-down; CSV and PDF export.
- E-mail (Resend, SMTP or SendGrid) in English and Arabic: urgent tasks, meetings, unread messages, password
  reset; per-person preferences.
- Meeting requests (1–3 proposed times; accept, decline, counter-propose) and a private live chat between each
  employee and the managers (WebSocket, read receipts).
- Website (`website/`, Next.js): public pages in English and Arabic (right-to-left), dark and light; sign-up,
  sign-in, password reset; the portal (overview, reports, employees, meetings, messages).
- Desktop app: offline outbox for work sessions, connection banner, Windows Credential Manager for the sign-in.
- Production: start script (migrations, app role), `/health/ready`, refusal of insecure production settings,
  encrypted daily database backups with a tested restore, CI for the service and the website.

### Changed
- AI Chat general questions are answered by an online model (`openai/gpt-oss-120b` at Groq) through the company's
  server; questions about your own data are still answered from the data, on the PC's classifier.
- Only program names (never window titles) are sent with sessions.
- New passwords need at least 10 characters.
- PyTorch 2.14.1 (CUDA 13.0); all dependencies audited with no known vulnerabilities.

### Removed
- The local Qwen2.5-1.5B model (the installer is about 3 GB smaller).
- The separate admin program and the demo accounts.


## 1.0.0 — 2026-10

First release as an installable Windows application.

### Added
- Offline Windows installer (PyInstaller + Inno Setup) with all AI models bundled; `packaging/`, `tools/fetch_models.py`.
- `app_paths.py`: user data and logs in `%LOCALAPPDATA%\OfficeAssistant` when installed; rotating log file.
- Application icon; Office Assistant Admin as a second program.
- Summariser and translator load local model copies (`models/hf/`) — no internet needed.
- Documentation: README, INSTALL, USER_GUIDE, DEVELOPMENT, DEPLOYMENT, TESTING, TROUBLESHOOTING, licences.

### Changed
- New GUI designed in Figma: new colour palette (dark and light), line icons, redesigned pages.
- `requirements.txt` pinned to the tested versions.

### Earlier milestones
- AI Chat: Qwen2.5-1.5B local model with a router (database engine vs. model), streaming, stop, chat history.
- Knowledge: BM25 search over manager documents with visibility rules and source citations.
- Code-quality refactoring (SOLID, repositories, threading rules) and a 167-test pytest suite.
- Sessions with camera (YOLO) + window tracking, tasks with deadlines, calendar, reports, AI Helper.
