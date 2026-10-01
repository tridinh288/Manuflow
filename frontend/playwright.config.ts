import { defineConfig } from '@playwright/test'

/**
 * End-to-end demo through the real UI (Phase 8 DoD). Needs the full stack with a freshly
 * seeded database: `docker compose up -d`, `docker compose exec api python -m seed`, then
 * `E2E_PASSWORD=<SEED_DEMO_PASSWORD> npm run e2e`. Not part of CI (no seeded stack there).
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
})
