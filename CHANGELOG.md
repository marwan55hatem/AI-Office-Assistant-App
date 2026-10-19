# Changelog

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
