import { describe, expect, it } from "vitest";
import { isWorkflowSubmissionAllowed, workflowSubmissionBlockedReason } from "./workflowReadiness";
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

describe("isWorkflowSubmissionAllowed", () => {
  it("allows submission when all dependencies are healthy", () => {
    expect(isWorkflowSubmissionAllowed(status({ state: "ready", readiness: readiness({}) }))).toBe(true);
  });

  it("blocks submission while checking", () => {
    expect(isWorkflowSubmissionAllowed(status({ state: "checking" }))).toBe(false);
  });

  it("blocks submission when the API process is unavailable", () => {
    expect(isWorkflowSubmissionAllowed(status({ state: "unavailable" }))).toBe(false);
  });

  it("allows submission when degraded solely due to Redis", () => {
    expect(
      isWorkflowSubmissionAllowed(status({ state: "degraded", readiness: readiness({ redis: "unavailable" }) })),
    ).toBe(true);
  });

  it("blocks submission when Qdrant is unavailable (the policy half of every combined request needs it)", () => {
    expect(
      isWorkflowSubmissionAllowed(status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) })),
    ).toBe(false);
  });

  it("blocks submission when Postgres is unavailable (the structured half of every combined request needs it)", () => {
    expect(
      isWorkflowSubmissionAllowed(
        status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
      ),
    ).toBe(false);
  });

  it("blocks submission when both Qdrant and Postgres are unavailable", () => {
    expect(
      isWorkflowSubmissionAllowed(
        status({
          state: "degraded",
          readiness: readiness({ qdrant: "unavailable", postgresql: "unavailable" }),
        }),
      ),
    ).toBe(false);
  });
});

describe("workflowSubmissionBlockedReason", () => {
  it("returns null when submission is allowed", () => {
    expect(workflowSubmissionBlockedReason(status({ state: "ready" }))).toBeNull();
    expect(
      workflowSubmissionBlockedReason(
        status({ state: "degraded", readiness: readiness({ redis: "unavailable" }) }),
      ),
    ).toBeNull();
  });

  it("returns a reason while checking or unavailable", () => {
    expect(workflowSubmissionBlockedReason(status({ state: "checking" }))).toMatch(/checking/i);
    expect(workflowSubmissionBlockedReason(status({ state: "unavailable" }))).toMatch(/unavailable/i);
  });

  it("names the search index when Qdrant is down", () => {
    expect(
      workflowSubmissionBlockedReason(
        status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) }),
      ),
    ).toMatch(/search index/i);
  });

  it("names the database when Postgres is down", () => {
    expect(
      workflowSubmissionBlockedReason(
        status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
      ),
    ).toMatch(/database/i);
  });

  it("mentions both when Qdrant and Postgres are both down", () => {
    const reason = workflowSubmissionBlockedReason(
      status({
        state: "degraded",
        readiness: readiness({ qdrant: "unavailable", postgresql: "unavailable" }),
      }),
    );
    expect(reason).toMatch(/search index/i);
    expect(reason).toMatch(/database/i);
  });
});
