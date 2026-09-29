import { describe, expect, it } from "vitest";
import { assistantSubmissionBlockedReason, isAssistantSubmissionAllowed } from "./assistantReadiness";
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

describe("isAssistantSubmissionAllowed", () => {
  it("allows submission when ready", () => {
    expect(isAssistantSubmissionAllowed(status({ state: "ready", readiness: readiness({}) }))).toBe(
      true,
    );
  });

  it("blocks submission while checking", () => {
    expect(isAssistantSubmissionAllowed(status({ state: "checking" }))).toBe(false);
  });

  it("blocks submission when the backend is unavailable", () => {
    expect(isAssistantSubmissionAllowed(status({ state: "unavailable" }))).toBe(false);
  });

  it("allows submission when degraded solely due to Redis", () => {
    expect(
      isAssistantSubmissionAllowed(
        status({ state: "degraded", readiness: readiness({ redis: "unavailable" }) }),
      ),
    ).toBe(true);
  });

  it("allows submission when degraded due to Postgres (policy route may still work)", () => {
    expect(
      isAssistantSubmissionAllowed(
        status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
      ),
    ).toBe(true);
  });

  it("allows submission when degraded due to Qdrant (structured routes may still work)", () => {
    expect(
      isAssistantSubmissionAllowed(
        status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) }),
      ),
    ).toBe(true);
  });
});

describe("assistantSubmissionBlockedReason", () => {
  it("returns null whenever submission is allowed, including every degraded case", () => {
    expect(assistantSubmissionBlockedReason(status({ state: "ready" }))).toBeNull();
    expect(
      assistantSubmissionBlockedReason(
        status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
      ),
    ).toBeNull();
    expect(
      assistantSubmissionBlockedReason(
        status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) }),
      ),
    ).toBeNull();
  });

  it("returns a reason while checking or unavailable", () => {
    expect(assistantSubmissionBlockedReason(status({ state: "checking" }))).toMatch(/checking/i);
    expect(assistantSubmissionBlockedReason(status({ state: "unavailable" }))).toMatch(
      /unavailable/i,
    );
  });
});
