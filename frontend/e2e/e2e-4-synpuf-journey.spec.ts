import { expect, test } from "./fixtures";
import { KNOWN_SYNPUF_BENEFICIARY_ID, SYNPUF_ASSISTANT_QUESTION } from "./fixtures";

/**
 * E2E-4: SynPUF structured assistant query -> structured UI.
 *
 * Mirrors E2E-3 for the other dataset. Uses a real, already-ingested
 * Phase 8 dev-subset SynPUF beneficiary ID (re-verified live against the
 * classifier during this slice's audit).
 */
test.describe("E2E-4: SynPUF structured assistant journey", () => {
  test("a free-text SynPUF question routes to the real SynPUF tool and renders synthetic/sample-labeled structured data", async ({
    page,
  }) => {
    await page.goto("/assistant");
    await expect(page.getByRole("heading", { name: /careflow assistant/i })).toBeVisible();

    const submit = page.getByRole("button", { name: "Ask CareFlow" });
    await expect(submit).toBeEnabled();

    await page.getByLabel("Your request").fill(SYNPUF_ASSISTANT_QUESTION);
    await submit.click();

    // Real backend round trip -- the real beneficiary_id renders back in
    // the structured record itself (a <dt>...</dt><dd>...</dd> pair).
    // Scoped to the <dd> tag specifically because the same ID text also
    // legitimately appears in the submitted-question echo and the
    // "example request" chip -- this locator targets only the actual
    // result data, not those incidental occurrences.
    await expect(
      page.locator("dd").filter({ hasText: KNOWN_SYNPUF_BENEFICIARY_ID }),
    ).toBeVisible({ timeout: 15_000 });

    // Synthetic/sample-data labeling must be visible on a structured
    // SynPUF result.
    await expect(page.getByText(/synthetic, de-identified demonstration claims data/i)).toBeVisible();

    // No FHIR linkage anywhere in the rendered result.
    await expect(page.getByText(/patient_id/i)).not.toBeVisible();
    await expect(page.getByText(/synthea_fhir/i)).not.toBeVisible();
  });
});
