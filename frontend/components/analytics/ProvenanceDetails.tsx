import styles from "./ProvenanceDetails.module.css";

/**
 * An expandable <details> block listing provenance fields as plain
 * label/value pairs. Only fields the caller explicitly passes are shown
 * -- this component never invents a field, and the caller is responsible
 * for only passing fields the backend actually returned (no machine-
 * specific or sensitive environment data -- see
 * backend/app/analytics/snapshot.py's own review of environment.json).
 */
export function ProvenanceDetails({
  summary,
  fields,
}: {
  summary: string;
  fields: { label: string; value: string }[];
}) {
  return (
    <details className={styles.details}>
      <summary className={styles.summary}>{summary}</summary>
      <dl className={styles.fieldList}>
        {fields.map((field) => (
          <div key={field.label} style={{ display: "contents" }}>
            <dt>{field.label}</dt>
            <dd>{field.value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
