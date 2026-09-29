import { formatCurrencyUsd, formatDateOnly, formatText, formatTimestamp } from "@/lib/formatting";
import type { FieldSpec } from "./fieldTypes";
import styles from "./RecordFields.module.css";

function formatByKind(value: unknown, kind: FieldSpec["kind"]): string {
  switch (kind) {
    case "date":
      return formatDateOnly(value as string | null);
    case "timestamp":
      return formatTimestamp(value as string | null);
    case "money":
      return formatCurrencyUsd(value as number | null);
    default:
      return formatText(value as string | number | null);
  }
}

interface RecordFieldsProps<T extends object> {
  record: T;
  fields: FieldSpec[];
  /** Fields whose backend value is null/undefined are skipped entirely by
   * default (many FHIR/SynPUF fields are legitimately optional and mostly
   * absent) -- pass true to render "—" for them instead. */
  showEmpty?: boolean;
}

/** A single record's fields as a definition list -- reused for both a
 * one-record "summary" card and each item in a list result, so
 * Encounters/Conditions/Procedures/etc. never need their own bespoke
 * layout component (see docs/phase14_frontend_design.md's "Structured
 * rendering"). Only backend-returned field values are ever shown. */
export function RecordFields<T extends object>({
  record,
  fields,
  showEmpty = false,
}: RecordFieldsProps<T>) {
  const asRecord = record as unknown as Record<string, unknown>;
  return (
    <dl className={styles.fields}>
      {fields.map((field) => {
        const value = asRecord[field.key];
        if (!showEmpty && (value === null || value === undefined)) return null;
        return (
          <div key={field.key} className={styles.field}>
            <dt>{field.label}</dt>
            <dd>{formatByKind(value, field.kind)}</dd>
          </div>
        );
      })}
    </dl>
  );
}
