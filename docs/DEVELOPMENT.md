# Development

## Setup (Windows, Python 3.12)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu124
pip install -r requirements-dev.txt          # pytest, pyflakes
python tools/fetch_models.py                 # Qwen2.5-1.5B, BART, 12 MarianMT pairs, YOLO12n -> models/ (~8 GB)
```

`python tools/fetch_models.py --check` lists what is present. Without an NVIDIA GPU, install the CPU wheels
of torch/torchvision instead (drop the `--extra-index-url`).

## Run

```bash
python main.py            # the application (data in ./data/office_assistant.db)
python admin.py           # admin panel, password admin123
```

Useful environment variables:

| variable | effect |
|---|---|
| `OFFICE_LLM=0` | switch the chat language model off (engine-only answers) |
| `OFFICE_DATA_DIR=<folder>` | use another database/log folder |
| `OFFICE_MODELS_DIR=<folder>` | load the models from another folder |
| `APP_UI_SCALE=1` | disable the automatic UI zoom on big screens |

`app_paths.py` decides where files live: the project folder in development, `%LOCALAPPDATA%\OfficeAssistant`
for data and the bundle folder for models when installed.

## Everyday commands

```bash
python -m pytest tests/                      # 167 tests
python -m pyflakes main.py admin.py ui admin_ui database detection assistant chat knowledge llm tools tests
python database/db_manager.py                # database self-test
python tools/code_audit.py                   # code-quality numbers
python tools/generate_database_docs.py       # regenerate docs/DATABASE.md after schema changes
python tools/make_icon.py                    # regenerate assets/icons/app.ico
python -m assistant.train_intent             # retrain the chat intent classifier (writes assistant/intent_model.pt)
```

## Conventions
See [CLEAN_CODE.md](../CLEAN_CODE.md) and [SOLID_NOTES.md](../SOLID_NOTES.md). In short: only `database/` writes SQL,
widgets and the database are used from the Qt main thread only ([THREADING.md](THREADING.md)), new database methods
must be listed in `database/repositories.py` (a test enforces it), heavy libraries are imported lazily.

## Version control
The project is not a git repository yet. To start one: `git init`, then commit — `.gitignore` already
excludes `data/` (real database with passwords), `models/` (multi-GB weights), `build/` and `dist/`.
