import { describe, expect, it } from "vitest";
import { isReviewSurfaceAllowed, reviewSurfaceBlockedReason } from "./reviewReadiness";
import type { SystemStatus } from "./api/systemStatus";

function status(overrides: Partial<SystemStatus>): SystemStatus {
  return {
    state: "ready",
    liveness: null,
    readiness: null,
    requestId: null,
    error: null,
    ...overrides,
  };
}

function readiness(overrides: Partial<Record<"postgresql" | "qdrant" | "redis", string>>) {
  return {
    status: "unready" as const,
    service: "careflow-ai",
    version: "0.1.0",
    dependencies: {
      postgresql: { status: (overrides.postgresql ?? "ok") as "ok" | "unavailable" },
      qdrant: { status: (overrides.qdrant ?? "ok") as "ok" | "unavailable" },
      redis: { status: (overrides.redis ?? "ok") as "ok" | "unavailable" },
    },
  };
}

describe("isReviewSurfaceAllowed", () => {
  it("allows access when all dependencies are healthy", () => {
    expect(isReviewSurfaceAllowed(status({ state: "ready" }))).toBe(true);
  });

  it("blocks access while checking", () => {
    expect(isReviewSurfaceAllowed(status({ state: "checking" }))).toBe(false);
  });

  it("blocks access when the API process is unavailable", () => {
    expect(isReviewSurfaceAllowed(status({ state: "unavailable" }))).toBe(false);
  });

  it("blocks access when Postgres is unavailable", () => {
    expect(
      isReviewSurfaceAllowed(status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) })),
    ).toBe(false);
  });

  it("allows access when only Qdrant is unavailable (queue/detail/decision never touch it)", () => {
    expect(
      isReviewSurfaceAllowed(status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) })),
    ).toBe(true);
  });

  it("allows access when only Redis is unavailable", () => {
    expect(
      isReviewSurfaceAllowed(status({ state: "degraded", readiness: readiness({ redis: "unavailable" }) })),
    ).toBe(true);
  });
});

describe("reviewSurfaceBlockedReason", () => {
  it("returns null when access is allowed", () => {
    expect(reviewSurfaceBlockedReason(status({ state: "ready" }))).toBeNull();
    expect(
      reviewSurfaceBlockedReason(
        status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) }),
      ),
    ).toBeNull();
  });

  it("returns a reason while checking or unavailable", () => {
    expect(reviewSurfaceBlockedReason(status({ state: "checking" }))).toMatch(/checking/i);
    expect(reviewSurfaceBlockedReason(status({ state: "unavailable" }))).toMatch(/unavailable/i);
  });

  it("names the database when Postgres is down", () => {
    expect(
      reviewSurfaceBlockedReason(
        status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
      ),
    ).toMatch(/database/i);
  });
});
