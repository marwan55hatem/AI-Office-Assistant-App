# Hugging Face Space (Docker SDK) for the online service -- a host that needs no payment card.
# The Space holds only this file and README.md; it builds backend/ from the public GitHub branch.
# Secrets (MIGRATIONS_DATABASE_URL, APP_ROLE_PASSWORD, JWT_SECRET, WEB_PROXY_SECRET, GROQ_API_KEY,
# RESEND_API_KEY) and settings go in the Space's "Variables and secrets"; see docs/PRODUCTION.md.
# To pick up new commits: Space settings -> "Factory rebuild".
FROM python:3.12-slim

ARG REPO=https://github.com/marwan55hatem/AI-Office-Assistant-App.git
ARG BRANCH=cloud-upgrade

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=7860
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && git clone --depth 1 --branch "$BRANCH" "$REPO" /tmp/repo \
    && mkdir -p /srv && cp -r /tmp/repo/backend/. /srv/ \
    && rm -rf /tmp/repo && apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
RUN pip install --no-cache-dir -r requirements.txt

# Spaces run the container as user 1000
RUN useradd --create-home --uid 1000 api && chown -R api /srv
USER api

EXPOSE 7860
CMD ["python", "scripts/start.py"]
