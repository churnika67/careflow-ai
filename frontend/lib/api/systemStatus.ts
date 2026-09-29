/**
 * Maps GET /live and GET /ready onto the frontend's system-status states.
 *
 * Semantics (see docs/phase14_frontend_design.md's "System status
 * semantics" for the full rationale):
 *
 *   checking     - a request is in flight (this module never returns
 *                  this state itself -- it's the caller's initial state
 *                  before fetchSystemStatus() resolves).
 *   ready        - GET /ready succeeded with status="ready".
 *   degraded     - the API process is reachable (GET /live succeeded)
 *                  but readiness is not satisfied -- either /ready
 *                  responded with status="unready", or /ready itself
 *                  could not be completed even though /live could.
 *   unavailable  - GET /live itself could not be reached, timed out, or
 *                  failed at the network level.
 *
 * Redis optionality (Phase 13's own principle) is not special-cased here
 * at all: backend/app/services/health.py::check_readiness() already
 * never lets a Redis failure affect ReadinessResponse.status, so simply
 * trusting that field is correct and sufficient -- this module must not
 * reimplement or second-guess that backend decision.
 */

import { apiGet } from "./client";
import { ApiClientError } from "./errors";
import type { LivenessResponse, ReadinessResponse } from "./types";

export type SystemStatusState = "checking" | "ready" | "degraded" | "unavailable";

export interface SystemStatus {
  state: SystemStatusState;
  liveness: LivenessResponse | null;
  readiness: ReadinessResponse | null;
  requestId: string | null;
  error: string | null;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiClientError) {
    return err.message;
  }
  return "CareFlow backend is currently unavailable.";
}

function requestIdOf(err: unknown): string | null {
  return err instanceof ApiClientError ? (err.requestId ?? null) : null;
}

export async function fetchSystemStatus(signal?: AbortSignal): Promise<SystemStatus> {
  let live: Awaited<ReturnType<typeof apiGet<LivenessResponse>>>;
  try {
    live = await apiGet<LivenessResponse>("/live", { signal });
  } catch (err) {
    return {
      state: "unavailable",
      liveness: null,
      readiness: null,
      requestId: requestIdOf(err),
      error: errorMessage(err),
    };
  }

  if (!live.ok) {
    // /live is documented to always return 200 when reachable at all --
    // anything else is treated conservatively as unavailable rather than
    // guessed at.
    return {
      state: "unavailable",
      liveness: null,
      readiness: null,
      requestId: live.requestId,
      error: `CareFlow backend responded unexpectedly to /live (status ${live.status}).`,
    };
  }

  try {
    const ready = await apiGet<ReadinessResponse>("/ready", { signal });
    return {
      state: ready.ok && ready.data.status === "ready" ? "ready" : "degraded",
      liveness: live.data,
      readiness: ready.data,
      requestId: ready.requestId,
      error: null,
    };
  } catch (err) {
    // The process itself answered /live, so this is a degraded reading,
    // not a full outage.
    return {
      state: "degraded",
      liveness: live.data,
      readiness: null,
      requestId: requestIdOf(err) ?? live.requestId,
      error: errorMessage(err),
    };
  }
}
