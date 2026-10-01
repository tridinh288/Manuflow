# Manuflow web (Phase 8)

A demo UI for the backend (B17). It holds **no business rules**: menus come from the
`permissions` in `/auth/me`, order buttons from `allowed_actions`, and every number on screen
comes from the API.

```bash
docker compose up -d web          # http://localhost:5173, talks to the API on :8000
# or, without Docker:
npm ci && npm run dev
```

| Script | What it does |
| --- | --- |
| `npm run gen:api` | Regenerates `src/api/schema.d.ts` from `docs/openapi.json` |
| `npm run check:api` | Same, and fails if the committed types are stale (CI) |
| `npm run typecheck` / `lint` / `test` / `build` | `tsc`, `oxlint`, `vitest`, production build |

When the API changes: `docker compose exec -T api python scripts/export_openapi.py >
docs/openapi.json`, then `npm run gen:api`.

Every form submission gets a fresh `Idempotency-Key`, reused only when the same submission is
retried after a network error or a 5xx (`src/lib/useSubmit.ts`). The access token is kept in
`sessionStorage`, so it ends with the browser tab.
