/**
 * Deliberate, tested formatting for structured healthcare fields --
 * see docs/phase14_frontend_design.md's "Date handling"/"Money handling".
 *
 * DATE-only backend fields (e.g. birth_date, from_date -- Postgres DATE
 * columns, serialized as "YYYY-MM-DD" with no time component) are never
 * passed through `new Date(...)`: doing so parses as UTC midnight, and a
 * negative-UTC-offset browser timezone would then display the PREVIOUS
 * calendar day -- a real, well-known bug class. These are rendered
 * verbatim as the string the backend returned.
 *
 * TIMESTAMPTZ fields (e.g. period_start, effective_datetime) carry real
 * timezone information and are safe to format via `Date`.
 */

import type { Coding } from "./api/orchestrationTypes";

export function formatDateOnly(value: string | null | undefined): string {
  if (!value) return "—";
  return value;
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatCurrencyUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

export function formatText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

/** "<display> (<system> <code>)" when a display exists, else "<system> <code>". */
export function formatCoding(code: string, codeSystem: string, codeDisplay: string | null): string {
  if (codeDisplay) return `${codeDisplay} (${codeSystem} ${code})`;
  return `${codeSystem} ${code}`;
}

export function formatCodingList(codings: Coding[] | null | undefined): string {
  if (!codings || codings.length === 0) return "—";
  return codings.map((c) => formatCoding(c.code, c.system, c.display)).join("; ");
}
