import { describe, expect, it } from "vitest";
import { isStructuredAnalyticsAllowed, structuredAnalyticsBlockedReason } from "./structuredAnalyticsReadiness";
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

describe("isStructuredAnalyticsAllowed", () => {
  it("allows access when everything is healthy", () => {
    expect(isStructuredAnalyticsAllowed(status({ state: "ready" }))).toBe(true);
  });

  it("blocks access while checking", () => {
    expect(isStructuredAnalyticsAllowed(status({ state: "checking" }))).toBe(false);
  });

  it("blocks access when the API process is unavailable", () => {
    expect(isStructuredAnalyticsAllowed(status({ state: "unavailable" }))).toBe(false);
  });

  it("blocks access when Postgres is unavailable -- the endpoint goes straight to Postgres", () => {
    expect(
      isStructuredAnalyticsAllowed(
        status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
      ),
    ).toBe(false);
  });

  it("allows access when only Qdrant is unavailable -- structured analytics never touches Qdrant", () => {
    expect(
      isStructuredAnalyticsAllowed(status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) })),
    ).toBe(true);
  });

  it("allows access when only Redis is unavailable", () => {
    expect(
      isStructuredAnalyticsAllowed(status({ state: "degraded", readiness: readiness({ redis: "unavailable" }) })),
    ).toBe(true);
  });
});

describe("structuredAnalyticsBlockedReason", () => {
  it("returns null when access is allowed", () => {
    expect(structuredAnalyticsBlockedReason(status({ state: "ready" }))).toBeNull();
    expect(
      structuredAnalyticsBlockedReason(
        status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) }),
      ),
    ).toBeNull();
  });

  it("returns a reason while checking or unavailable", () => {
    expect(structuredAnalyticsBlockedReason(status({ state: "checking" }))).toMatch(/checking/i);
    expect(structuredAnalyticsBlockedReason(status({ state: "unavailable" }))).toMatch(/unavailable/i);
  });

  it("names the database when Postgres is down", () => {
    expect(
      structuredAnalyticsBlockedReason(
        status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
      ),
    ).toMatch(/database/i);
  });
});
