import { describe, expect, it } from "vitest";
import { isPolicySubmissionAllowed, policySubmissionBlockedReason } from "./policyReadiness";
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

const READY_ALL_HEALTHY: SystemStatus = status({
  state: "ready",
  readiness: {
    status: "ready",
    service: "careflow-ai",
    version: "0.1.0",
    dependencies: {
      postgresql: { status: "ok" },
      qdrant: { status: "ok" },
      redis: { status: "ok" },
    },
  },
});

const DEGRADED_REDIS_DOWN: SystemStatus = status({
  state: "degraded",
  readiness: {
    status: "unready", // won't actually happen per backend (redis never gates it), but this module must not depend on that
    service: "careflow-ai",
    version: "0.1.0",
    dependencies: {
      postgresql: { status: "ok" },
      qdrant: { status: "ok" },
      redis: { status: "unavailable" },
    },
  },
});

const DEGRADED_POSTGRES_DOWN: SystemStatus = status({
  state: "degraded",
  readiness: {
    status: "unready",
    service: "careflow-ai",
    version: "0.1.0",
    dependencies: {
      postgresql: { status: "unavailable" },
      qdrant: { status: "ok" },
      redis: { status: "ok" },
    },
  },
});

const DEGRADED_QDRANT_DOWN: SystemStatus = status({
  state: "degraded",
  readiness: {
    status: "unready",
    service: "careflow-ai",
    version: "0.1.0",
    dependencies: {
      postgresql: { status: "ok" },
      qdrant: { status: "unavailable" },
      redis: { status: "ok" },
    },
  },
});

describe("isPolicySubmissionAllowed", () => {
  it("allows submission when ready with all dependencies healthy", () => {
    expect(isPolicySubmissionAllowed(READY_ALL_HEALTHY)).toBe(true);
  });

  it("blocks submission while checking", () => {
    expect(isPolicySubmissionAllowed(status({ state: "checking" }))).toBe(false);
  });

  it("blocks submission when unavailable", () => {
    expect(isPolicySubmissionAllowed(status({ state: "unavailable" }))).toBe(false);
  });

  it("allows submission when degraded solely due to Redis", () => {
    expect(isPolicySubmissionAllowed(DEGRADED_REDIS_DOWN)).toBe(true);
  });

  it("allows submission when degraded solely due to Postgres (policy does not need it)", () => {
    expect(isPolicySubmissionAllowed(DEGRADED_POSTGRES_DOWN)).toBe(true);
  });

  it("blocks submission when degraded because Qdrant is explicitly unavailable", () => {
    expect(isPolicySubmissionAllowed(DEGRADED_QDRANT_DOWN)).toBe(false);
  });
});

describe("policySubmissionBlockedReason", () => {
  it("returns null when submission is allowed", () => {
    expect(policySubmissionBlockedReason(READY_ALL_HEALTHY)).toBeNull();
    expect(policySubmissionBlockedReason(DEGRADED_REDIS_DOWN)).toBeNull();
  });

  it("returns a reason while checking", () => {
    expect(policySubmissionBlockedReason(status({ state: "checking" }))).toMatch(/checking/i);
  });

  it("returns a reason when unavailable", () => {
    expect(policySubmissionBlockedReason(status({ state: "unavailable" }))).toMatch(/unavailable/i);
  });

  it("returns a Qdrant-specific reason when degraded due to Qdrant", () => {
    const reason = policySubmissionBlockedReason(DEGRADED_QDRANT_DOWN);
    expect(reason).toBeTruthy();
    expect(reason).not.toMatch(/not covered|no coverage/i);
  });
});
