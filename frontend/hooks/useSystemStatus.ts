"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchSystemStatus, type SystemStatus } from "@/lib/api/systemStatus";

const CHECKING: SystemStatus = {
  state: "checking",
  liveness: null,
  readiness: null,
  requestId: null,
  error: null,
};

/**
 * Fetches system status once on mount and exposes a manual `refresh`.
 * No automatic polling -- see docs/phase14_frontend_design.md's "Loading
 * UX" for why a deliberate, conservative choice was made not to poll in
 * this foundation slice.
 */
export function useSystemStatus() {
  const [status, setStatus] = useState<SystemStatus>(CHECKING);
  const abortRef = useRef<AbortController | null>(null);

  // No synchronous setState call in this function's own body -- only
  // inside the async .then() callback -- so it is safe to call directly
  // from the mount effect below.
  const load = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    fetchSystemStatus(controller.signal).then((result) => {
      if (!controller.signal.aborted) {
        setStatus(result);
      }
    });
  }, []);

  // Safe here: invoked only from the Refresh button's click handler, a
  // user event, never from an effect body.
  const refresh = useCallback(() => {
    setStatus(CHECKING);
    load();
  }, [load]);

  useEffect(() => {
    load();
    return () => abortRef.current?.abort();
  }, [load]);

  return { status, refresh };
}
