import styles from "./StatusBadge.module.css";

export type BadgeState = "checking" | "ok" | "degraded" | "unavailable";

const SYMBOLS: Record<BadgeState, string> = {
  checking: "…", // ellipsis
  ok: "●", // filled circle
  degraded: "▲", // triangle
  unavailable: "✕", // cross
};

interface StatusBadgeProps {
  state: BadgeState;
  label: string;
}

/**
 * A status indicator that never relies on color alone: each state has its
 * own symbol and text label (see docs/phase14_frontend_design.md's
 * "Accessibility approach").
 */
export function StatusBadge({ state, label }: StatusBadgeProps) {
  return (
    <span className={`${styles.badge} ${styles[state]}`}>
      <span aria-hidden="true" className={styles.symbol}>
        {SYMBOLS[state]}
      </span>
      <span>{label}</span>
    </span>
  );
}
