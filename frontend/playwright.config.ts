import { defineConfig, devices } from "@playwright/test";

/**
 * Phase 16 Slice 2: the first bounded browser E2E suite.
 *
 * Chromium only -- no Firefox/WebKit matrix (see
 * docs/phase16_testing_ci_design.md's Slice 1 "Cross-browser scope"
 * section: no cross-browser-specific behavior has ever been observed in
 * this project, and expanding is a one-line addition later if a real
 * need appears).
 *
 * `channel` is read from PLAYWRIGHT_BROWSER_CHANNEL, left undefined by
 * default. Undefined means Playwright's own bundled Chromium (the
 * correct default for CI, where `npx playwright install chromium`
 * downloads it once from a reachable CDN). Some sandboxed local
 * environments cannot reach that CDN at all but do have a system Google
 * Chrome already installed -- set PLAYWRIGHT_BROWSER_CHANNEL=chrome to
 * launch that instead, with zero download. Chrome and Chromium share the
 * same Blink/V8 engine, so this is a legitimate, Playwright-documented
 * substitution, not a different browser family.
 *
 * No retries by default, anywhere -- a flaky-looking local result must
 * be diagnosed, never hidden by re-running until green (see this
 * design's own flaky-test-audit precedent in docs/phase16_testing_ci_design.md).
 *
 * `trace: "retain-on-failure"`, not `"on-first-retry"` -- verified
 * empirically (Phase 16 Slice 3), not assumed: `"on-first-retry"` only
 * records a trace on a test's *first retry attempt*, and with
 * `retries: 0` a test is never retried at all, so a genuine failure
 * produced a screenshot but zero trace file. `"retain-on-failure"`
 * records a trace for every test and keeps only the ones for tests that
 * actually failed -- the correct choice when retries stay at 0 and a
 * real failure still needs to be diagnosable.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || undefined,
      },
    },
  ],
  webServer: {
    command: "npm run build && npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
