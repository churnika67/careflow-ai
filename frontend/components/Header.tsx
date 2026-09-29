"use client";

import { useSystemStatusContext } from "./SystemStatusProvider";
import { StatusBadge, type BadgeState } from "./StatusBadge";
import type { SystemStatusState } from "@/lib/api/systemStatus";
import styles from "./Header.module.css";

const STATE_TO_BADGE: Record<SystemStatusState, { state: BadgeState; label: string }> = {
  checking: { state: "checking", label: "Checking system status…" },
  ready: { state: "ok", label: "Ready" },
  degraded: { state: "degraded", label: "Degraded" },
  unavailable: { state: "unavailable", label: "Unavailable" },
};

export function Header() {
  const { status } = useSystemStatusContext();
  const badge = STATE_TO_BADGE[status.state];

  return (
    <header className={styles.header}>
      <div>
        <p className={styles.title}>CareFlow AI</p>
        <p className={styles.subtitle}>Healthcare Intelligence Platform</p>
      </div>
      <div aria-live="polite">
        <StatusBadge state={badge.state} label={badge.label} />
      </div>
    </header>
  );
}
