# Office Assistant API (backend)

FastAPI + PostgreSQL (SQLAlchemy 2, Alembic). Multi-company: every company's data is
isolated twice, by the repositories and by PostgreSQL Row-Level Security.

## Run locally

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
docker compose up -d db                      # PostgreSQL 17 on localhost:55432
copy .env.example .env                       # then fill in the values
alembic upgrade head                         # as the owner (MIGRATIONS_DATABASE_URL)
python scripts/create_app_role.py            # the restricted role the API connects as
uvicorn app.main:app --reload                # http://localhost:8000/docs
```

`.env` needs `APP_ROLE_PASSWORD` for the role script. The API refuses to start when
`DATABASE_URL` uses a role that bypasses Row-Level Security.

## Tests

```bash
docker compose up -d db
python -m pytest                             # builds a fresh office_test database each run
```

## Layout

| folder | contents |
|---|---|
| `app/core` | settings, Argon2 + JWT, rate limiter, auth dependencies |
| `app/db` | models (all tables), engine and the per-transaction tenant setting |
| `app/repositories` | `TenantRepository` (always filters by `company_id`) and one repository per table |
| `app/services` | account logic: register, login, refresh rotation, logout, join |
| `app/routers` | `/auth`, `/users`, `/invites`, `/company`, `/health` |
| `alembic/versions` | migrations; `0001` also creates the RLS policies and the login/join lookup functions |
| `scripts/create_app_role.py` | creates the application's database role (no superuser, no BYPASSRLS) |

## Tenant isolation

* The company id comes only from the signed access token. Request bodies reject unknown
  fields, so `company_id` or `role` cannot be sent.
* `TenantRepository` adds `WHERE company_id = <token company>` to every query and stamps it
  on every insert.
* Every tenant table has `ENABLE` + `FORCE ROW LEVEL SECURITY` with a policy comparing
  `company_id` to the transaction setting `app.company_id`, set at the start of each request's
  single transaction (`set_config(..., true)`, so it cannot leak through the connection pool).
* Foreign keys are composite `(company_id, id)`, so a row cannot reference another company's user.
* Login and joining run before the company is known; they use `SECURITY DEFINER` functions
  that return only the columns needed. **The migration owner must be a superuser or have
  BYPASSRLS** for these functions to see the rows; the app role must have neither.

## API (Phase 1)

| method | path | who |
|---|---|---|
| POST | `/auth/register-company` | anyone: creates the company and its manager |
| POST | `/auth/login`, `/auth/refresh`, `/auth/logout` | anyone (rate-limited login) |
| POST | `/auth/join` | anyone with an invite token or the company code; account stays *pending* |
| GET | `/auth/me` | signed in |
| GET | `/users`, `/users/{id}` | manager (employees: only themselves) |
| POST | `/users/{id}/approve` | manager |
| PATCH | `/users/{id}/status` | manager: `active` / `disabled` (disabling revokes sessions) |
| POST/GET/DELETE | `/invites`, `/invites/{id}` | manager; the token is shown once and stored hashed |
| GET/POST | `/company`, `/company/join-code` | manager |
