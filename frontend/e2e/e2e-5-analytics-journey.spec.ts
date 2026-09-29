import { expect, test } from "./fixtures";

/**
 * E2E-5: Analytics -> evaluation snapshot + structured analytics.
 *
 * Verifies both independently-loaded panels render, using stable
 * semantic labels (dataset names, claim-matrix categories, the runtime
 * configuration drift warning, the provenance disclosure control, and
 * top-5 wording) rather than re-asserting every exact number the
 * component tests already cover.
 */
test.describe("E2E-5: Analytics journey", () => {
  test("both the Evaluation Snapshot and Structured Analytics panels render with real data", async ({
    page,
  }) => {
    await page.goto("/analytics");
    await expect(page.getByRole("heading", { name: "Analytics & Evaluation" })).toBeVisible();

    // --- Evaluation Snapshot: stable semantic labels -----------------
    await expect(page.getByRole("heading", { name: "Evaluation Snapshot" })).toBeVisible();
    await expect(page.getByText(/Phase 12 Evaluation Snapshot/)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("heading", { name: "Development / regression set" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Held-out set" })).toBeVisible();

    // Claim matrix categories -- names, not the numbers already covered
    // by component tests. Scoped to the <dt> tag specifically since
    // plain text search ambiguously matches unrelated prose elsewhere on
    // this content-dense page (e.g. "...an unsupported/out-of-corpus
    // case...").
    await expect(page.getByRole("heading", { name: "Claim Matrix" })).toBeVisible();
    const claimMatrixTerms = page.locator("dt");
    await expect(claimMatrixTerms.filter({ hasText: /^Supported$/ })).toBeVisible();
    await expect(claimMatrixTerms.filter({ hasText: /^Partially supported$/ })).toBeVisible();
    await expect(claimMatrixTerms.filter({ hasText: /^Not evaluated$/ })).toBeVisible();
    await expect(claimMatrixTerms.filter({ hasText: /^Out of scope$/ })).toBeVisible();

    // Runtime configuration drift must be visible, not merely present in
    // the DOM.
    await expect(page.getByText("Runtime configuration drift")).toBeVisible();
    // Appears twice by design: its own highlighted card, and again in the
    // full grouped gap list -- either is sufficient proof of visibility.
    await expect(page.getByText(/EVAL-RUNTIME-CONFIG-DRIFT/).first()).toBeVisible();

    // Evaluation Provenance disclosure control is present (collapsed by
    // default -- see the component-test-level interaction coverage for
    // the expand behavior itself).
    await expect(
      page.getByText("Show experiment metadata and evaluated configuration"),
    ).toBeVisible();

    // --- Structured Analytics: synthetic/sample labeling + top-5 -----
    await expect(
      page.getByRole("heading", { name: "Structured Analytics", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Synthetic FHIR Population Analytics" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" }),
    ).toBeVisible();
    await expect(page.getByText(/Synthea-generated synthetic FHIR data/)).toBeVisible();
    await expect(page.getByText(/CMS DE-SynPUF synthetic\/sample claims data/)).toBeVisible();
    await expect(page.getByText(/^Top 5 /).first()).toBeVisible();

    // Neither panel's failure hides the other -- both rendered above in
    // the same page load, from two independent API calls.
    await expect(page.getByText(/temporarily unavailable/i)).not.toBeVisible();
  });
});
