# Development

Three parts, each with its own setup: the desktop app (this folder), the online service
([`backend/`](../backend/README.md)) and the website ([`website/`](../website/README.md)).

## Desktop app (Windows, Python 3.12)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu130
pip install -r requirements-dev.txt          # pytest, pyflakes
python tools/fetch_models.py                 # BART, 12 MarianMT pairs, YOLO12n -> models/ (~5 GB)
```

`python tools/fetch_models.py --check` lists what is present. Without an NVIDIA GPU, install the CPU wheels
of torch/torchvision instead (drop the `--extra-index-url`).

## Run

```bash
# 1. the online service with its database (Docker): see backend/README.md
# 2. the desktop app against it
set OFFICE_API_URL=http://localhost:8000
python main.py
```

Useful environment variables:

| variable | effect |
|---|---|
| `OFFICE_API_URL=<url>` | the online service (default: the address the installer was built with, else `http://localhost:8000`) |
| `OFFICE_BACKEND=local` | run against the old single-PC SQLite database instead of the service (development only) |
| `OFFICE_LLM=0` | switch the AI Chat's online model off (answers only from your data) |
| `OFFICE_DATA_DIR=<folder>` | use another folder for the outbox and logs |
| `OFFICE_MODELS_DIR=<folder>` | load the local models from another folder |
| `APP_UI_SCALE=1` | disable the automatic UI zoom on big screens |

`app_paths.py` decides where files live: the project folder in development, `%LOCALAPPDATA%\OfficeAssistant`
for data and the bundle folder for models when installed. `cloud/config.py` decides which service the app
talks to.

## Everyday commands

```bash
python -m pytest tests/                      # desktop tests
python -m pyflakes main.py ui database detection assistant chat knowledge llm cloud tools tests
python self_check.py                         # load and run every local model once
python tools/code_audit.py                   # code-quality numbers
python tools/generate_database_docs.py       # regenerate docs/DATABASE.md (local SQLite schema)
python tools/make_icon.py                    # regenerate assets/icons/app.ico
python -m assistant.train_intent             # retrain the chat intent classifier (writes assistant/intent_model.pt)
```

Service and website: `cd backend && python -m pytest`, `cd website && npm run lint && npm run typecheck && npm test`.

## Conventions
See [CLEAN_CODE.md](../CLEAN_CODE.md) and [SOLID_NOTES.md](../SOLID_NOTES.md). In short: screens use the
repositories (`database/repositories.py`), which are backed by the online service (`cloud/`) or, in local
mode, by SQLite; widgets are used from the Qt main thread only ([THREADING.md](THREADING.md)); heavy
libraries are imported lazily. On the service, every company-owned table is protected by Row-Level
Security and must be added to the isolation tests.

## Version control
Work for version 2 happened on the `cloud-upgrade` branch; [CHANGELOG-cloud.md](CHANGELOG-cloud.md) records
each phase. `.gitignore` excludes `data/`, `models/`, `build/`, `dist/` and every `.env` file.
