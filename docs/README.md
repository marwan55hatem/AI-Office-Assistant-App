# Documentation

For users:

| document | read it for |
|---|---|
| [INSTALL.md](INSTALL.md) | requirements, installing, first start, where the data is, update, uninstall |
| [USER_GUIDE.md](USER_GUIDE.md) | every screen for employees and managers, in the app and on the website |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | common problems (connection, sign-in, camera, models, e-mail) and their fixes |
| [PRIVACY.md](PRIVACY.md) | what stays on the PC, what goes online, who can see what |

For developers:

| document | read it for |
|---|---|
| [DEVELOPMENT.md](DEVELOPMENT.md) | setting up from source, environment variables, everyday commands |
| [PRODUCTION.md](PRODUCTION.md) | deploying the online service and the website, settings, backups, security checklist |
| [DEPLOYMENT.md](DEPLOYMENT.md) | building the Windows installer and the release checklist |
| [CHANGELOG-cloud.md](CHANGELOG-cloud.md) | how version 2 (online, multi-company) was built, phase by phase |
| [TESTING.md](TESTING.md) | the automated tests and the manual acceptance checklist |
| [ARCHITECTURE.md](ARCHITECTURE.md) | the module map, the layers, how data flows, where to extend |
| [DATABASE.md](DATABASE.md) | the local SQLite database of version 1 / local mode (generated); the online schema is in `backend/alembic/versions/` |
| [AI_STACK.md](AI_STACK.md) | each AI model used: what it does, why this one, how it is run |
| [THREADING.md](THREADING.md) | which code runs on which thread and the rules that keep it safe |
| [DESIGN.md](DESIGN.md) | the GUI design system (colours, type, components, Figma file) |

Project-level files (in the project root):

| file | content |
|---|---|
| `README.md` | overview and quick start |
| `backend/README.md`, `website/README.md` | the online service and the website |
| `CHANGELOG.md` | what changed in each version |
| `LICENSE`, `THIRD_PARTY_NOTICES.md` | licences of this code and of the bundled models, libraries and online services |
| `quality_audit_before.md` / `quality_audit_after.md` | the code audit before and after the refactoring |
| `SOLID_NOTES.md`, `CLEAN_CODE.md` | design principles and conventions used in the code base |
