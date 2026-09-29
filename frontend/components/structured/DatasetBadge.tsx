import styles from "./DatasetBadge.module.css";

interface DatasetBadgeProps {
  name: "Synthea FHIR" | "CMS DE-SynPUF";
}

/** Always names the real source dataset plus "Synthetic" -- never a vague
 * label like "Patient Database" (see docs/phase14_frontend_design.md's
 * "Synthetic-data labeling"). */
export function DatasetBadge({ name }: DatasetBadgeProps) {
  return (
    <span className={styles.badge}>
      {name} <span className={styles.synthetic}>· Synthetic</span>
    </span>
  );
}
