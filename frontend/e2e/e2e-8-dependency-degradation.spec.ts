import { execFileSync } from "node:child_process";
import { expect, test } from "./fixtures";

/**
 * E2E-8: dependency readiness degradation, against the real developer
 * Docker stack's Postgres and Redis containers.
 *
 * Two claims, both load-bearing to Phase 13's "Redis is an optional
 * performance dependency, Postgres/Qdrant are authoritative" rule (see
 * backend/app/services/health.py::check_readiness), proven live rather
 * than only at the unit/component level:
 *
 *   1. Stopping Redis alone leaves GET /ready (and the UI's System
 *      Status) reporting ready -- non-authoritative.
 *   2. Stopping Postgres (the more deterministic of the two authoritative
 *      dependencies to test: it has a real Docker healthcheck, unlike
 *      Qdrant) makes /ready unavailable and the UI reflect it -- then
 *      recovers once Postgres is restored.
 *
 * Every container this test stops is restored in a `finally` block, and
 * the test polls each container's own Docker healthcheck (not a fixed
 * sleep) before proceeding, so a crash mid-test still leaves the stack
 * recoverable and the suite never finishes with a dependency left down.
 * Nothing here touches container volumes or data -- `docker stop`/`docker
 * start` only, never `rm`, `down`, or `down -v`.
 */

// Defaults target the developer stack's own container names. Overridable
// so this same test can run unmodified against the isolated clean-bootstrap
// stack (careflow-ai-e2e-clean-{redis,postgres}-1) when E2E_BASE_URL points
// the frontend at that stack's backend instead.
const REDIS_CONTAINER = process.env.E2E_REDIS_CONTAINER ?? "careflow-ai-redis-1";
const POSTGRES_CONTAINER = process.env.E2E_POSTGRES_CONTAINER ?? "careflow-ai-postgres-1";
const HEALTH_POLL_TIMEOUT_MS = 60_000;
const HEALTH_POLL_INTERVAL_MS = 2_000;

function dockerStop(container: string): void {
  execFileSync("docker", ["stop", container], { stdio: "pipe" });
}

function dockerStart(container: string): void {
  execFileSync("docker", ["start", container], { stdio: "pipe" });
}

function containerHealth(container: string): string {
  try {
    return execFileSync("docker", ["inspect", container, "--format", "{{.State.Health.Status}}"], {
      stdio: "pipe",
    })
      .toString()
      .trim();
  } catch {
    return "unknown";
  }
}

async function waitForHealthy(container: string): Promise<void> {
  const deadline = Date.now() + HEALTH_POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (containerHealth(container) === "healthy") return;
    await new Promise((resolve) => setTimeout(resolve, HEALTH_POLL_INTERVAL_MS));
  }
  throw new Error(`${container} did not report healthy within ${HEALTH_POLL_TIMEOUT_MS}ms`);
}

test.describe("E2E-8: dependency readiness degradation", () => {
  test("Redis down is non-authoritative; Postgres down makes readiness unavailable; both recover", async ({
    page,
    allowConsoleError,
  }) => {
    // Scoped to exactly the expected failure this intentional-degradation
    // journey produces -- the browser's own network-layer log of GET
    // /ready responding 503 while Postgres is deliberately stopped below.
    // Never a blanket suppression: any other console error still fails
    // the test.
    allowConsoleError(/status of 503 \(Service Unavailable\)/);

    // Baseline: fully ready before touching anything.
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "System Status" })).toBeVisible();
    await expect(page.getByText("Available").first()).toBeVisible({ timeout: 15_000 });

    try {
      // --- Step 1: Redis down -> readiness stays "ready" (non-authoritative). ---
      dockerStop(REDIS_CONTAINER);
      try {
        await expect
          .poll(
            async () => {
              await page.getByRole("button", { name: "Refresh" }).click();
              const badge = page.locator("li", { hasText: "Cache (Redis)" });
              return (await badge.textContent()) ?? "";
            },
            { timeout: 30_000, intervals: [1_000] },
          )
          .toContain("Unavailable");

        // Overall system status must still be "Ready" -- Redis never gates it.
        await expect(page.locator("li", { hasText: "API" }).getByText("Reachable")).toBeVisible();
        await expect(
          page.locator("li", { hasText: "Postgres" }).getByText("Available"),
        ).toBeVisible();
        await expect(
          page.locator("li", { hasText: "Qdrant" }).getByText("Available"),
        ).toBeVisible();
      } finally {
        dockerStart(REDIS_CONTAINER);
        await waitForHealthy(REDIS_CONTAINER);
      }

      // Confirm Redis recovery is reflected before moving to the next step.
      await expect
        .poll(
          async () => {
            await page.getByRole("button", { name: "Refresh" }).click();
            const badge = page.locator("li", { hasText: "Cache (Redis)" });
            return (await badge.textContent()) ?? "";
          },
          { timeout: 30_000, intervals: [1_000] },
        )
        .toContain("Available");

      // --- Step 2: Postgres down -> readiness becomes unavailable. -------------
      dockerStop(POSTGRES_CONTAINER);
      try {
        await expect
          .poll(
            async () => {
              await page.getByRole("button", { name: "Refresh" }).click();
              const badge = page.locator("li", { hasText: "Postgres" }).first();
              return (await badge.textContent().catch(() => "")) ?? "";
            },
            { timeout: 30_000, intervals: [1_000] },
          )
          .toContain("Unavailable");
      } finally {
        dockerStart(POSTGRES_CONTAINER);
        await waitForHealthy(POSTGRES_CONTAINER);
      }

      // --- Step 3: recovery -> readiness returns to fully ready. ---------------
      await expect
        .poll(
          async () => {
            await page.getByRole("button", { name: "Refresh" }).click();
            const badge = page.locator("li", { hasText: "Postgres" }).first();
            return (await badge.textContent().catch(() => "")) ?? "";
          },
          { timeout: 30_000, intervals: [1_000] },
        )
        .toContain("Available");
      await expect(page.locator("li", { hasText: "Cache (Redis)" }).getByText("Available")).toBeVisible();
      await expect(page.locator("li", { hasText: "Qdrant" }).getByText("Available")).toBeVisible();
    } finally {
      // Belt-and-suspenders: guarantee both containers are left running no
      // matter which step above threw.
      if (containerHealth(REDIS_CONTAINER) !== "healthy") {
        dockerStart(REDIS_CONTAINER);
      }
      if (containerHealth(POSTGRES_CONTAINER) !== "healthy") {
        dockerStart(POSTGRES_CONTAINER);
      }
      await waitForHealthy(REDIS_CONTAINER);
      await waitForHealthy(POSTGRES_CONTAINER);
    }
  });
});
