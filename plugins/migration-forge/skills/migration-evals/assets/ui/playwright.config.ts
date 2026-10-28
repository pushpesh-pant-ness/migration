import { defineConfig, devices } from '@playwright/test';

// BASE_URL and FORGE_SIDE (legacy | new) are set by evals_run.py for each side of a ui_e2e case.
export default defineConfig({
  testDir: './specs',
  fullyParallel: false,          // both sides share seeded data; keep flows sequential
  retries: 0,                    // a flaky parity test is a finding, not something to retry away
  timeout: 60_000,
  use: {
    baseURL: process.env.BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // Golden screenshots come from the legacy run, so both sides resolve to the same path.
  snapshotPathTemplate: '{testDir}/__golden__/{testFilePath}/{arg}{ext}',
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.02, animations: 'disabled' } },
  outputDir: `./test-results/${process.env.FORGE_SIDE ?? 'local'}`,
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
