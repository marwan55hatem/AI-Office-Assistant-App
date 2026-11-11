FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 api
USER api

EXPOSE 8000
# scripts/start.py: migrations (when MIGRATIONS_DATABASE_URL is set), the app role, then uvicorn on $PORT
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3   CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health/ready' % os.environ.get('PORT','8000'), timeout=4)"
CMD ["python", "scripts/start.py"]
