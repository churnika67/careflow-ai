import { formatText } from "@/lib/formatting";
import styles from "./RecordFields.module.css";

/**
 * The smallest generic, safe fallback for a structured result whose tool
 * this frontend has no dedicated FieldSpec[] for (Phase 14 Slice 4,
 * section 29) -- never a raw JSON dump, but also never a hard-coded
 * per-tool renderer for every possible registry entry. Builds its field
 * list dynamically from the object's own keys; every value is rendered as
 * plain text via the same formatText() used elsewhere, never parsed or
 * interpreted (a nested object/array becomes its JSON string form, still
 * never executed as HTML/Markdown).
 */
export function GenericRecordFields({ record }: { record: Record<string, unknown> }) {
  return (
    <dl className={styles.fields}>
      {Object.entries(record).map(([key, value]) => (
        <div key={key} className={styles.field}>
          <dt>{key}</dt>
          <dd>
            {value === null || value === undefined
              ? "—"
              : typeof value === "object"
                ? JSON.stringify(value)
                : formatText(value as string | number)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
