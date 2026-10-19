# Documentation

For users:

| document | read it for |
|---|---|
| [INSTALL.md](INSTALL.md) | requirements, installing, first start, where the data is, update, uninstall |
| [USER_GUIDE.md](USER_GUIDE.md) | every screen for employees, managers and the admin panel |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | common problems (camera, GPU, models, database) and their fixes |
| [PRIVACY.md](PRIVACY.md) | what is collected, what is never stored, who can see what |

For developers:

| document | read it for |
|---|---|
| [DEVELOPMENT.md](DEVELOPMENT.md) | setting up from source, environment variables, everyday commands |
| [DEPLOYMENT.md](DEPLOYMENT.md) | building the offline Windows installer and the release checklist |
| [TESTING.md](TESTING.md) | the automated tests and the manual acceptance checklist |
| [ARCHITECTURE.md](ARCHITECTURE.md) | the module map, the layers, how data flows, where to extend |
| [DATABASE.md](DATABASE.md) | every table, the migrations and every database method (generated) |
| [AI_STACK.md](AI_STACK.md) | each AI model used: what it does, why this one, how it is run |
| [THREADING.md](THREADING.md) | which code runs on which thread and the rules that keep it safe |
| [DESIGN.md](DESIGN.md) | the GUI design system (colours, type, components, Figma file) |

Project-level files (in the project root):

| file | content |
|---|---|
| `README.md` | overview and quick start |
| `CHANGELOG.md` | what changed in each version |
| `LICENSE`, `THIRD_PARTY_NOTICES.md` | licences of this code and of the bundled models/libraries |
| `quality_audit_before.md` / `quality_audit_after.md` | the code audit before and after the refactoring |
| `SOLID_NOTES.md`, `CLEAN_CODE.md` | design principles and conventions used in the code base |
