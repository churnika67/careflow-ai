import { expect, test } from "./fixtures";
import { KNOWN_FHIR_PATIENT_ID, KNOWN_POLICY_QUESTION } from "./fixtures";

/**
 * E2E-6: the combined POLICY_AND_STRUCTURED multi-agent workflow.
 *
 * Runs a real Medicare policy question together with exactly one
 * structured domain (Synthetic FHIR) for the same request -- never FHIR
 * and SynPUF together, and never implying the two evidence sources
 * describe the same person (see docs/phase10_multi_agent_design.md's
 * dataset-boundary rule, reinforced again here per the Phase 16 Slice 3
 * directive).
 *
 * Reuses the same golden policy question (E2E-2) and known FHIR patient
 * ID (E2E-3) already proven live elsewhere in this suite, combined for
 * the first time into one /reviewable-query request via the real
 * /workflow page.
 *
 * Critical safety assertion: this test must never assert or imply that
 * Medicare policy applies TO the synthetic patient, a coverage
 * determination, medical necessity, or eligibility -- it only asserts
 * that both evidence sources rendered, independently, and that the
 * application's own safety disclaimer is visible making that same point
 * to the user.
 */
test.describe("E2E-6: multi-agent policy + structured workflow", () => {
  test("a combined policy + FHIR request renders both evidence sources as separate, validated sections", async ({
    page,
  }) => {
    await page.goto("/workflow");
    await expect(page.getByRole("heading", { name: "Evidence Workflow" })).toBeVisible();

    await page.getByLabel("Policy question").fill(KNOWN_POLICY_QUESTION);
    await page.getByLabel("Synthetic FHIR").check();
    await page.getByLabel("Synthetic Patient ID").fill(KNOWN_FHIR_PATIENT_ID);

    const submit = page.getByRole("button", { name: "Run Evidence Workflow" });
    await expect(submit).toBeEnabled();
    await submit.click();

    // Real backend round trip through the real multi-agent graph.
    await expect(page.getByText("Workflow: Medicare Policy + Synthetic Data")).toBeVisible({
      timeout: 20_000,
    });

    // --- Policy evidence section: present, scoped to its own <section> --
    const policySection = page.locator("section", { has: page.getByRole("heading", { name: "Medicare Policy Evidence" }) });
    await expect(policySection).toBeVisible();
    await expect(policySection.getByText("Citation 1")).toBeVisible();
    await expect(policySection.getByText(/home use of oxygen/i)).toBeVisible();

    // --- Structured evidence section: present, scoped to its own <section>,
    // and carrying the real FHIR patient id back from the real tool call.
    const structuredSection = page.locator("section", {
      has: page.getByRole("heading", { name: "Synthetic Healthcare Data" }),
    });
    await expect(structuredSection).toBeVisible();
    await expect(structuredSection.locator("dd").filter({ hasText: KNOWN_FHIR_PATIENT_ID })).toBeVisible();
    await expect(structuredSection.getByText(/generated synthetic healthcare data/i)).toBeVisible();

    // --- Validation result: present. -------------------------------------
    await expect(page.getByRole("heading", { name: "Validation" })).toBeVisible();
    await expect(page.getByText(/validation (passed|did not pass)/i)).toBeVisible();

    // --- The two sections are visually separate, real DOM sections (each
    // scoped above to its own <h2>), never merged into one -- and the
    // application's own safety disclaimer is shown alongside them.
    await expect(page.getByRole("note")).toContainText(
      "Policy information and synthetic healthcare data are shown as separate evidence sources.",
    );
    await expect(page.getByRole("note")).toContainText(
      "Their presence together does not establish individual coverage, eligibility, medical",
    );

    // --- Phase 10 safety boundary: this test never asserts, and the
    // rendered page never states, that Medicare policy applies TO this
    // synthetic patient, or any coverage/eligibility/medical-necessity
    // determination -- only that the disclaimer against exactly that
    // interpretation is itself visible (already asserted above).
    await expect(page.getByText(/this patient is covered/i)).not.toBeVisible();
    await expect(page.getByText(/patient is eligible/i)).not.toBeVisible();
    await expect(page.getByText(/medically necessary for this patient/i)).not.toBeVisible();
  });
});
