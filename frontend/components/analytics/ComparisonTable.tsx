import { MetricValue } from "./MetricValue";
import styles from "./ComparisonTable.module.css";

export interface ComparisonRow {
  key: string;
  label: string;
  cells: (number | string | null | undefined)[];
}

/**
 * A generic mode-by-metric comparison table. Every numeric cell renders
 * through MetricValue so a genuine null/undefined stays "Not evaluated"
 * rather than becoming a blank cell or a silent 0.
 */
export function ComparisonTable({
  caption,
  columnHeadings,
  rows,
}: {
  caption: string;
  columnHeadings: string[];
  rows: ComparisonRow[];
}) {
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Mode</th>
            {columnHeadings.map((heading) => (
              <th scope="col" key={heading}>
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <th scope="row">{row.label}</th>
              {row.cells.map((cell, index) => (
                <td key={index}>
                  <MetricValue value={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
