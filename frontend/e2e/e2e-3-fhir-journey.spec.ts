import { expect, test } from "./fixtures";
import { FHIR_ASSISTANT_QUESTION, KNOWN_FHIR_PATIENT_ID } from "./fixtures";

/**
 * E2E-3: FHIR structured assistant query -> structured UI.
 *
 * Uses a real, already-ingested Phase 8 dev-subset FHIR patient ID
 * (re-verified live against the classifier during this slice's audit),
 * through the actual user-facing CareFlow Assistant free-text surface --
 * never the explicit Patient Data lookup page, and never a mocked
 * response.
 */
test.describe("E2E-3: FHIR structured assistant journey", () => {
  test("a free-text FHIR question routes to the real FHIR tool and renders synthetic-labeled structured data", async ({
    page,
  }) => {
    await page.goto("/assistant");
    await expect(page.getByRole("heading", { name: /careflow assistant/i })).toBeVisible();

    const submit = page.getByRole("button", { name: "Ask CareFlow" });
    await expect(submit).toBeEnabled();

    await page.getByLabel("Your request").fill(FHIR_ASSISTANT_QUESTION);
    await submit.click();

    // Real backend round trip -- the real patient_id renders back in the
    // structured record itself (a <dt>Patient ID</dt><dd>...</dd> pair).
    // Scoped to the <dd> tag specifically because the same ID text also
    // legitimately appears in the submitted-question echo and the
    // "example request" chip -- this locator targets only the actual
    // result data, not those incidental occurrences.
    await expect(
      page.locator("dd").filter({ hasText: KNOWN_FHIR_PATIENT_ID }),
    ).toBeVisible({ timeout: 15_000 });

    // Synthetic-data labeling must be visible on a structured FHIR result.
    await expect(
      page.getByText(/generated synthetic healthcare data and do not represent real patients/i),
    ).toBeVisible();

    // No SynPUF linkage anywhere in the rendered result.
    await expect(page.getByText(/beneficiary_id/i)).not.toBeVisible();
    await expect(page.getByText(/cms_desynpuf/i)).not.toBeVisible();
  });
});
