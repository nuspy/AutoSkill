import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// End-to-end tests drive the real frontend against a real backend started with AUTOSKILL_LLM_FAKE=demo
// (canned model answers), a temporary SQLite database, inline jobs and the console email backend.
const ROOT = path.resolve(__dirname, "..");
const BACKEND_PY = process.env.AUTOSKILL_E2E_PYTHON || (existsSync(path.join(ROOT, "backend/.venv/bin/python")) ? path.join(ROOT, "backend/.venv/bin/python") : "python");
const DATA = process.env.AUTOSKILL_E2E_DATA || path.join(ROOT, "frontend/test-results/e2e-data");
const API_PORT = process.env.AUTOSKILL_E2E_API_PORT || "8877";
const WEB_PORT = process.env.AUTOSKILL_E2E_WEB_PORT || "5177";
const chromium = process.env.PLAYWRIGHT_CHROMIUM_PATH || (existsSync("/opt/pw-browsers/chromium/chrome") ? "/opt/pw-browsers/chromium/chrome" : undefined);

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    locale: "en-US",
    trace: "retain-on-failure",
    ...(chromium ? { launchOptions: { executablePath: chromium } } : {}),
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${BACKEND_PY} -m uvicorn autoskill.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: path.join(ROOT, "backend"),
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        AUTOSKILL_ENV: "test",
        AUTOSKILL_DATABASE_URL: `sqlite+aiosqlite:///${DATA}/e2e.db`,
        AUTOSKILL_DATA_DIR: `${DATA}/data`,
        AUTOSKILL_JOBS: "inline",
        AUTOSKILL_EVENTS: "memory",
        AUTOSKILL_LLM_FAKE: "demo",
        AUTOSKILL_EMAIL_BACKEND: "console",
        AUTOSKILL_SECRET_KEY: "e2e-secret-key-not-for-production-0123456789",
        AUTOSKILL_PUBLIC_URL: `http://127.0.0.1:${WEB_PORT}`,
        AUTOSKILL_CORS_ORIGINS: `["http://127.0.0.1:${WEB_PORT}"]`,
        AUTOSKILL_E2E_RESET: "1",
      },
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { VITE_API_URL: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
