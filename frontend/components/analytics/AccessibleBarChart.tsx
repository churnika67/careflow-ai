import styles from "./AccessibleBarChart.module.css";

export interface BarChartRow {
  key: string;
  label: string;
  value: number | null | undefined;
  /** Already-formatted display text, e.g. "0.88 (22/25)" or "Not evaluated". */
  displayText: string;
}

/**
 * A restrained, dependency-free bar visualization. Every bar's numeric
 * value is rendered as real text next to it (never conveyed by color or
 * bar length alone) -- this is the "equivalent screen-reader-accessible
 * values" requirement in place of a separate hidden data table, since the
 * value is already ordinary DOM text a screen reader announces normally.
 * A `null`/`undefined` value renders a flat, muted "not evaluated" bar,
 * never a bar of length 0 that could be misread as a measured zero.
 */
export function AccessibleBarChart({ rows, maxValue = 1 }: { rows: BarChartRow[]; maxValue?: number }) {
  return (
    <div className={styles.chart}>
      {rows.map((row) => {
        const notEvaluated = row.value === null || row.value === undefined;
        const pct = notEvaluated ? 0 : Math.max(0, Math.min(100, (row.value! / maxValue) * 100));
        return (
          <div
            key={row.key}
            className={notEvaluated ? `${styles.row} ${styles.notEvaluatedRow}` : styles.row}
          >
            <span className={styles.label}>{row.label}</span>
            <span className={styles.track}>
              <span className={styles.fill} style={{ width: `${pct}%` }} />
            </span>
            <span className={styles.value}>{row.displayText}</span>
          </div>
        );
      })}
    </div>
  );
}
