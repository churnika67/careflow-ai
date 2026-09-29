export type FieldKind = "text" | "date" | "timestamp" | "money";

export interface FieldSpec {
  key: string;
  label: string;
  kind?: FieldKind;
}
