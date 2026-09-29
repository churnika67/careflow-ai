"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import type { SystemStatus } from "@/lib/api/systemStatus";

interface SystemStatusContextValue {
  status: SystemStatus;
  refresh: () => void;
}

const SystemStatusContext = createContext<SystemStatusContextValue | null>(null);

/**
 * Fetches system status exactly once for the whole app shell, so the
 * header badge and the System Overview page's detailed panel always
 * agree -- neither owns a separate, independently-timed fetch.
 */
export function SystemStatusProvider({ children }: { children: ReactNode }) {
  const { status, refresh } = useSystemStatus();
  return (
    <SystemStatusContext.Provider value={{ status, refresh }}>
      {children}
    </SystemStatusContext.Provider>
  );
}

export function useSystemStatusContext(): SystemStatusContextValue {
  const value = useContext(SystemStatusContext);
  if (!value) {
    throw new Error("useSystemStatusContext must be used within a SystemStatusProvider");
  }
  return value;
}
