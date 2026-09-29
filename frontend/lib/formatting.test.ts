import { describe, expect, it } from "vitest";
import {
  formatCodingList,
  formatCoding,
  formatCurrencyUsd,
  formatDateOnly,
  formatText,
  formatTimestamp,
} from "./formatting";

describe("formatDateOnly", () => {
  it("preserves a DATE-only string verbatim, never reinterpreting via timezone", () => {
    expect(formatDateOnly("2020-01-15")).toBe("2020-01-15");
  });

  it("renders an em dash for null/undefined", () => {
    expect(formatDateOnly(null)).toBe("—");
    expect(formatDateOnly(undefined)).toBe("—");
  });
});

describe("formatTimestamp", () => {
  it("formats a real ISO timestamp deliberately (date + time)", () => {
    const result = formatTimestamp("2020-01-15T10:30:00+00:00");
    expect(result).not.toBe("2020-01-15T10:30:00+00:00");
    expect(result).toMatch(/2020/);
  });

  it("renders an em dash for null/undefined", () => {
    expect(formatTimestamp(null)).toBe("—");
  });

  it("falls back to the raw string for an unparseable value rather than throwing", () => {
    expect(formatTimestamp("not-a-date")).toBe("not-a-date");
  });
});

describe("formatCurrencyUsd", () => {
  it("formats a monetary value as USD currency", () => {
    expect(formatCurrencyUsd(1234.5)).toBe("$1,234.50");
  });

  it("formats zero correctly", () => {
    expect(formatCurrencyUsd(0)).toBe("$0.00");
  });

  it("renders an em dash for null/undefined, never $0 by accident", () => {
    expect(formatCurrencyUsd(null)).toBe("—");
    expect(formatCurrencyUsd(undefined)).toBe("—");
  });
});

describe("formatText", () => {
  it("passes through a non-empty value", () => {
    expect(formatText("hospital")).toBe("hospital");
    expect(formatText(42)).toBe("42");
  });

  it("renders an em dash for null/undefined/empty string", () => {
    expect(formatText(null)).toBe("—");
    expect(formatText(undefined)).toBe("—");
    expect(formatText("")).toBe("—");
  });
});

describe("formatCoding", () => {
  it("includes the display when present", () => {
    expect(formatCoding("44054006", "http://snomed.info/sct", "Diabetes")).toBe(
      "Diabetes (http://snomed.info/sct 44054006)",
    );
  });

  it("falls back to system + code only when no display exists", () => {
    expect(formatCoding("44054006", "http://snomed.info/sct", null)).toBe(
      "http://snomed.info/sct 44054006",
    );
  });

  it("never fabricates a description that was not returned", () => {
    const result = formatCoding("99999", "http://example.com/custom-system", null);
    expect(result).not.toMatch(/n\/a|not available|no description/i);
  });
});

describe("formatCodingList", () => {
  it("joins multiple codings", () => {
    const result = formatCodingList([
      { system: "sys-a", code: "1", display: "First" },
      { system: "sys-b", code: "2", display: null },
    ]);
    expect(result).toBe("First (sys-a 1); sys-b 2");
  });

  it("renders an em dash for an empty or missing list", () => {
    expect(formatCodingList([])).toBe("—");
    expect(formatCodingList(null)).toBe("—");
    expect(formatCodingList(undefined)).toBe("—");
  });
});
