import { describe, expect, it } from "vitest";
import { isStructuredSubmissionAllowed, structuredSubmissionBlockedReason } from "./structuredReadiness";
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

describe("isStructuredSubmissionAllowed", () => {
  it("allows submission when ready", () => {
    expect(
      isStructuredSubmissionAllowed(status({ state: "ready", readiness: readiness({}) })),
    ).toBe(true);
  });

  it("blocks submission while checking", () => {
    expect(isStructuredSubmissionAllowed(status({ state: "checking" }))).toBe(false);
  });

  it("blocks submission when unavailable", () => {
    expect(isStructuredSubmissionAllowed(status({ state: "unavailable" }))).toBe(false);
  });

  it("blocks submission when degraded because Postgres is unavailable", () => {
    expect(
      isStructuredSubmissionAllowed(
        status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
      ),
    ).toBe(false);
  });

  it("keeps submission allowed when degraded solely due to Qdrant", () => {
    expect(
      isStructuredSubmissionAllowed(
        status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) }),
      ),
    ).toBe(true);
  });

  it("keeps submission allowed when degraded solely due to Redis", () => {
    expect(
      isStructuredSubmissionAllowed(
        status({ state: "degraded", readiness: readiness({ redis: "unavailable" }) }),
      ),
    ).toBe(true);
  });
});

describe("structuredSubmissionBlockedReason", () => {
  it("returns null when allowed", () => {
    expect(
      structuredSubmissionBlockedReason(status({ state: "ready", readiness: readiness({}) })),
    ).toBeNull();
  });

  it("mentions the database, not Qdrant/search, when Postgres is down", () => {
    const reason = structuredSubmissionBlockedReason(
      status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
    );
    expect(reason).toMatch(/database/i);
    expect(reason).not.toMatch(/search index|qdrant/i);
  });
});
