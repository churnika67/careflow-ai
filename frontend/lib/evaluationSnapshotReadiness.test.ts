import { describe, expect, it } from "vitest";
import { evaluationSnapshotBlockedReason, isEvaluationSnapshotAllowed } from "./evaluationSnapshotReadiness";
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

describe("isEvaluationSnapshotAllowed", () => {
  it("allows access when everything is healthy", () => {
    expect(isEvaluationSnapshotAllowed(status({ state: "ready" }))).toBe(true);
  });

  it("blocks access while checking", () => {
    expect(isEvaluationSnapshotAllowed(status({ state: "checking" }))).toBe(false);
  });

  it("blocks access when the API process is unavailable", () => {
    expect(isEvaluationSnapshotAllowed(status({ state: "unavailable" }))).toBe(false);
  });

  it("allows access when Postgres is unavailable -- the snapshot reads static files, never Postgres", () => {
    expect(
      isEvaluationSnapshotAllowed(
        status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
      ),
    ).toBe(true);
  });

  it("allows access when Qdrant is unavailable -- the snapshot never touches Qdrant", () => {
    expect(
      isEvaluationSnapshotAllowed(status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) })),
    ).toBe(true);
  });

  it("allows access when Redis is unavailable", () => {
    expect(
      isEvaluationSnapshotAllowed(status({ state: "degraded", readiness: readiness({ redis: "unavailable" }) })),
    ).toBe(true);
  });

  it("allows access even when every reported dependency is unavailable, since the API process itself is still reachable", () => {
    expect(
      isEvaluationSnapshotAllowed(
        status({
          state: "degraded",
          readiness: readiness({ postgresql: "unavailable", qdrant: "unavailable", redis: "unavailable" }),
        }),
      ),
    ).toBe(true);
  });
});

describe("evaluationSnapshotBlockedReason", () => {
  it("returns null when access is allowed, including every degraded-dependency combination", () => {
    expect(evaluationSnapshotBlockedReason(status({ state: "ready" }))).toBeNull();
    expect(
      evaluationSnapshotBlockedReason(
        status({ state: "degraded", readiness: readiness({ postgresql: "unavailable" }) }),
      ),
    ).toBeNull();
    expect(
      evaluationSnapshotBlockedReason(
        status({ state: "degraded", readiness: readiness({ qdrant: "unavailable" }) }),
      ),
    ).toBeNull();
  });

  it("returns a reason while checking or unavailable", () => {
    expect(evaluationSnapshotBlockedReason(status({ state: "checking" }))).toMatch(/checking/i);
    expect(evaluationSnapshotBlockedReason(status({ state: "unavailable" }))).toMatch(/unavailable/i);
  });
});
