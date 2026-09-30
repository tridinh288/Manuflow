# Manuflow — Manufacturing Production & Inventory Backend

This project is a student/personal simulation of an internal manufacturing management system. It models common workflows such as BOM management, material planning, inventory reservation, production planning, and workshop progress tracking. It is not a production ERP, and the author does not claim professional manufacturing experience.

> Status: **Phase 3 — master data and BOM** (in progress). Done: Phase 1 foundation; Phase 2
> authentication (JWT, lockout, permission matrix, user admin), append-only audit log and
> idempotent mutations; products, materials (with their zero inventory balance) and work
> centers with immutable codes and deactivate-only deletes.

## Quick start

Requirements: Docker Desktop (Compose v2).

```bash
cp .env.example .env          # placeholder values, fine for local development
docker compose up -d --build  # MySQL 8.0 + API; migrations run on API start
curl http://localhost:8000/health
# {"status":"ok","database":"ok"}
```

OpenAPI docs: <http://localhost:8000/docs>. MySQL is exposed on host port `3307`.

Create the first admin (the API cannot create users without one):

```bash
docker compose exec -e ADMIN_PASSWORD='choose-a-long-password' api   python -m app.cli create-user --username admin --full-name "System Admin"   --role ADMIN --password-env ADMIN_PASSWORD
```

The admin then manages users with `GET/POST /api/v1/users` and `PATCH /api/v1/users/{id}`.
Every route declares exactly one access rule (public, authenticated, or one permission
from the B4 matrix); a test walks the router and fails on any route that does not.

Idempotency (D-22): mutating requests accept an `Idempotency-Key` header (8-128 chars,
a UUID is recommended). The key row, the business change and the stored response commit
in one transaction, so a retry or double click returns the first response with
`Idempotent-Replayed: true` instead of repeating the change; reusing a key for a
different request is rejected with 422. Only successful responses are stored, and keys
expire after 24 hours (`python -m app.cli purge-idempotency-keys` reclaims the rows).

Authentication: `POST /api/v1/auth/login` with `{"username", "password"}` returns a 30-minute
bearer token; `GET /api/v1/auth/me` returns the caller, role and permissions. Five failed
logins within 15 minutes lock the account for 15 minutes; every failure returns the same
generic message. Audit rows are written in the same transaction as the change they
describe, never contain passwords or tokens, and MySQL triggers reject any UPDATE or DELETE.

## Tests and quality checks

```bash
docker compose exec api pytest -q                    # unit + API + integration (real MySQL)
docker compose exec api ruff check .
docker compose exec api ruff format --check .
docker compose exec api mypy
```

Integration tests run against a separate `manuflow_test` schema that Alembic rebuilds at
the start of every run; each test is rolled back afterwards. SQLite is not used, because
row locking and `CHECK` constraints must behave exactly like production (B2, B15).

`python scripts/rule_coverage.py` lists every business rule (`BR-xx`) of the spec and
the tests that cite it; a unit test fails if a rule of a completed phase has none.
Concurrency tests (`-m concurrency`) use two real MySQL connections on two threads.

CI (GitHub Actions) runs lint, type checks, `pip-audit` and the full test suite against a
MySQL 8.0 service container on every pull request.

## Project layout

```
backend/
  app/
    api/          thin routes, error mapping, dependencies
    core/         settings, request ID, logging, clock
    db/           declarative base, engine, session factory
    domain/       pure business logic, no I/O
    models/       SQLAlchemy models
    repositories/ queries and row locks, never commit
    schemas/      Pydantic request/response models
    services/     use cases; each owns one DB transaction
  alembic/        migrations (run with a separate DDL user)
  tests/          unit/ api/ integration/
docker/mysql/init/  creates databases and least-privilege DB users
docs/               requirements, decisions, AI usage log
```

## AI-assisted development

Built with Claude Code under the rules in [`CLAUDE.md`](CLAUDE.md): one branch and one
pull request per unit of work, tests for every business rule, CI on every PR, and a log
of AI mistakes caught in review in [`docs/ai-usage.md`](docs/ai-usage.md).
