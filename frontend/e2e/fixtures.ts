import { test as base, expect } from "@playwright/test";

/**
 * Phase 16 Slice 2 shared E2E fixtures.
 *
 * Known deterministic fixture identifiers -- reused from the SAME real,
 * already-ingested Phase 8 dev-subset data this project's own live-gated
 * pytest suite already depends on (tests/test_orchestration_api.py,
 * tests/test_agents_api.py), and cross-verified working against the live
 * backend during this slice's own audit. Never invented for this suite.
 */
export const KNOWN_FHIR_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713";
export const KNOWN_SYNPUF_BENEFICIARY_ID = "00013D2EFD8E45D1";

/**
 * A stable, exact_lexical-category question from the committed Phase 7/12
 * golden dataset (docs/evaluation/golden_retrieval_v1.json, case
 * cms-v1-009) -- Hit@1 was 1.0 across every retrieval mode for this case
 * per the Phase 12 audit, and it was re-verified against the live /query
 * endpoint during this slice's own work. Never an invented question.
 */
export const KNOWN_POLICY_QUESTION =
  "When arterial blood gas and oximetry studies conflict for home oxygen, which study is preferred?";
export const KNOWN_POLICY_EXPECTED_CHUNK_ID = "11f9eda3-b2d1-5c44-9ea4-a1b37768c254";

/**
 * Free-text Assistant phrasings that route deterministically through the
 * real classifier -- re-verified live (not merely mirrored from the
 * component-test mocks) during this slice's own audit.
 */
export const FHIR_ASSISTANT_QUESTION = `Show me FHIR patient ${KNOWN_FHIR_PATIENT_ID}`;
export const SYNPUF_ASSISTANT_QUESTION = `Look up SynPUF beneficiary ${KNOWN_SYNPUF_BENEFICIARY_ID}`;

type ConsoleAllowlist = { patterns: RegExp[] };

/**
 * Extends Playwright's own `test` with automatic page/console error
 * capture (Slice 2 directive's "console / page errors" requirement): any
 * uncaught page exception or console.error call fails the test, unless a
 * test explicitly opts a specific, investigated message out via
 * `allowConsoleError(pattern)`. No allowlist entries are pre-populated --
 * nothing in this project's actual component code calls console.error,
 * so any occurrence during E2E is worth failing loud on and
 * investigating, not silently tolerating.
 */
export const test = base.extend<{
  consoleAllowlist: ConsoleAllowlist;
  allowConsoleError: (pattern: RegExp) => void;
}>({
  consoleAllowlist: async ({}, use) => {
    await use({ patterns: [] });
  },
  allowConsoleError: async ({ consoleAllowlist }, use) => {
    await use((pattern: RegExp) => {
      consoleAllowlist.patterns.push(pattern);
    });
  },
  page: async ({ page, consoleAllowlist }, use) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];

    page.on("pageerror", (error) => {
      pageErrors.push(error.message);
    });
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push(message.text());
      }
    });

    await use(page);

    const isAllowed = (text: string) => consoleAllowlist.patterns.some((pattern) => pattern.test(text));
    const unexpectedPageErrors = pageErrors.filter((message) => !isAllowed(message));
    const unexpectedConsoleErrors = consoleErrors.filter((message) => !isAllowed(message));

    expect(
      unexpectedPageErrors,
      `Unexpected uncaught page error(s):\n${unexpectedPageErrors.join("\n")}`,
    ).toEqual([]);
    expect(
      unexpectedConsoleErrors,
      `Unexpected console.error call(s):\n${unexpectedConsoleErrors.join("\n")}`,
    ).toEqual([]);
  },
});

export { expect };
