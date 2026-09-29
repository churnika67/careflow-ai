import type { GapEntry, GapStatus } from "@/lib/api/analyticsTypes";
import styles from "./GapList.module.css";

const STATUS_LABELS: Record<GapStatus, string> = {
  OPEN: "Open",
  DOCUMENTED_LIMITATION: "Documented limitation",
  OUT_OF_SCOPE_PHASE12: "Out of scope (Phase 12)",
};

const STATUS_ORDER: GapStatus[] = ["OPEN", "DOCUMENTED_LIMITATION", "OUT_OF_SCOPE_PHASE12"];

/**
 * Groups gap-registry entries by status. Status is always paired with an
 * explicit text label (STATUS_LABELS) and rendered as a left border, not
 * a filled color block -- never color-only. `highlightGapId` is used to
 * prominently mark EVAL-RUNTIME-CONFIG-DRIFT without duplicating it.
 */
export function GapList({ entries, highlightGapId }: { entries: GapEntry[]; highlightGapId?: string }) {
  return (
    <div className={styles.group}>
      {STATUS_ORDER.map((status) => {
        const group = entries.filter((entry) => entry.status === status);
        if (group.length === 0) return null;
        return (
          <div key={status}>
            <h4 className={styles.groupHeading}>
              {STATUS_LABELS[status]} <span className={styles.groupCount}>({group.length})</span>
            </h4>
            <div className={styles.group}>
              {group.map((entry) => (
                <div
                  key={entry.gap_id}
                  className={
                    entry.gap_id === highlightGapId ? `${styles.entry} ${styles.highlighted}` : styles.entry
                  }
                  data-status={entry.status}
                >
                  <p className={styles.entryTitle}>{entry.title}</p>
                  <p className={styles.entryMeta}>
                    {entry.gap_id} · {entry.category}
                  </p>
                  <p className={styles.entryEvidence}>{entry.evidence}</p>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
