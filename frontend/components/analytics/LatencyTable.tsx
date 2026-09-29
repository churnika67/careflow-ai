import { MetricValue, formatMilliseconds } from "./MetricValue";
import styles from "../Analytics.module.css";

export interface LatencyStage {
  name: string;
  medianMs: number | null | undefined;
  p95Ms: number | null | undefined;
  calls: number | null | undefined;
}

/**
 * A plain accessible table for one latency category (retrieval, a set of
 * structured tools, multi-agent workflows, ...). Milliseconds are shown
 * consistently; a missing stage renders "Not evaluated" via MetricValue,
 * never a silent 0.
 */
export function LatencyTable({ caption, stages }: { caption: string; stages: LatencyStage[] }) {
  return (
    <div className={styles.tableScroll}>
      <table className={styles.table}>
        <caption className={styles.tableCaption}>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Stage</th>
            <th scope="col">Median</th>
            <th scope="col">p95</th>
            <th scope="col">Calls</th>
          </tr>
        </thead>
        <tbody>
          {stages.map((stage) => (
            <tr key={stage.name}>
              <td>{stage.name}</td>
              <td>
                <MetricValue value={stage.medianMs} format={formatMilliseconds} />
              </td>
              <td>
                <MetricValue value={stage.p95Ms} format={formatMilliseconds} />
              </td>
              <td>
                <MetricValue value={stage.calls} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
