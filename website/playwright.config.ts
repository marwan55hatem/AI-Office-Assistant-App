import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against a running website (WEB_URL, default http://localhost:3100) and
 * API (API_URL, default http://127.0.0.1:8766). Start both first:
 *   backend: docker compose up -d db; uvicorn app.main:app --port 8766
 *   website: npm run build; API_URL=http://127.0.0.1:8766 ALLOW_INSECURE_COOKIES=1 npx next start -p 3100
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 2,
  reporter: [["list"]],
  use: {
    baseURL: process.env.WEB_URL ?? "http://localhost:3100",
    trace: "retain-on-failure",
    locale: "en-US",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
