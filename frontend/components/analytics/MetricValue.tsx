import styles from "./MetricValue.module.css";

/**
 * The shared "not evaluated" semantic pattern (Phase 15 Slice 1
 * foundation requirement): a metric that is `null`/`undefined` in a
 * Phase 12 artifact means the underlying case count was zero for that
 * slice, or the value was never computed -- it must never render as 0%,
 * 0 ms, or a bare "N/A" with no explanation. Every caller passes the raw
 * value straight through; this component is the only place that decides
 * how an absent value looks.
 */
export function MetricValue({
  value,
  format,
  notEvaluatedLabel = "Not evaluated",
}: {
  value: number | string | null | undefined;
  format?: (value: number | string) => string;
  notEvaluatedLabel?: string;
}) {
  if (value === null || value === undefined) {
    return (
      <span className={styles.notEvaluated} title="No case in this evaluation set had a denominator for this metric">
        {notEvaluatedLabel}
      </span>
    );
  }
  return <span className={styles.rate}>{format ? format(value) : value}</span>;
}

export function formatRate(value: number | string): string {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return `${(numeric * 100).toFixed(1)}%`;
}

export function formatMilliseconds(value: number | string): string {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return `${numeric.toFixed(1)} ms`;
}
