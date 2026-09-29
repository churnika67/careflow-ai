import { expect, test } from "./fixtures";
import { KNOWN_POLICY_QUESTION, KNOWN_SYNPUF_BENEFICIARY_ID } from "./fixtures";
import { cleanupReviewIds } from "./reviewCleanup";

/**
 * E2E-7: the full HITL review lifecycle -- create -> queue -> detail ->
 * decision -> audit event -- driven entirely through the real UI against
 * the real backend and Postgres.
 *
 * Every review_id this test creates is tracked and deleted in a
 * try/finally block afterward via cleanupReviewIds() (scripts/
 * cleanup_review_ids.py, mirroring tests/test_review_api.py's
 * created_review_ids fixture exactly) -- the developer stack's baseline 4
 * review_cases / 8 review_events are never touched, and the suite-level
 * verification step re-checks the count returned to exactly 4/8 after
 * this test runs.
 */
test.describe("E2E-7: HITL review lifecycle", () => {
  test("a request flagged for human review can be found in the queue, decided, and audited", async ({
    page,
  }) => {
    const createdReviewIds: string[] = [];

    try {
      // --- Create: submit a combined workflow request with review
      // explicitly requested, deterministic regardless of validation
      // outcome. ---------------------------------------------------------
      await page.goto("/workflow");
      await page.getByLabel("Policy question").fill(KNOWN_POLICY_QUESTION);
      await page.getByLabel("Synthetic Claims").check();
      await page.getByLabel("Synthetic Beneficiary ID").fill(KNOWN_SYNPUF_BENEFICIARY_ID);
      await page.getByLabel("Request human review").check();

      const submit = page.getByRole("button", { name: "Run Evidence Workflow" });
      await expect(submit).toBeEnabled();
      await submit.click();

      await expect(page.getByText("Review required")).toBeVisible({ timeout: 20_000 });
      const viewReviewLink = page.getByRole("link", { name: "View review" });
      await expect(viewReviewLink).toBeVisible();
      const href = await viewReviewLink.getAttribute("href");
      expect(href).toMatch(/^\/reviews\/.+/);
      const reviewId = href!.replace("/reviews/", "");
      createdReviewIds.push(reviewId);

      // --- Queue: the new review is findable in the pending queue. ------
      await page.goto("/reviews");
      await expect(page.getByRole("heading", { name: "Reviews" })).toBeVisible();
      await expect(page.getByText(`Review ID: ${reviewId}`)).toBeVisible({ timeout: 15_000 });

      // --- Detail: open it from the queue itself (not by re-navigating
      // directly), landing on the review detail page. --------------------
      await page
        .locator("li", { hasText: `Review ID: ${reviewId}` })
        .getByRole("link", { name: "View review" })
        .click();
      await expect(page).toHaveURL(new RegExp(`/reviews/${reviewId}$`));
      await expect(page.getByRole("heading", { name: "Review", exact: true })).toBeVisible();
      await expect(page.getByText(`Review ID: ${reviewId}`)).toBeVisible();
      await expect(page.getByText("Pending", { exact: true })).toBeVisible();

      await expect(page.getByRole("heading", { name: "Audit History" })).toBeVisible();
      await expect(page.getByText("Review created")).toBeVisible();

      // --- Decision: approve as a named reviewer. ------------------------
      await page.getByLabel("Reviewer identifier").fill("e2e-slice3-reviewer");
      await page.getByLabel("Reason").fill("E2E-7 automated lifecycle check.");
      await page.getByRole("button", { name: "Approve" }).click();

      // --- Audit event: the decision is reflected in status and history. -
      await expect(page.getByText("This review has already been decided (Approved)")).toBeVisible({
        timeout: 15_000,
      });
      const auditHistory = page.locator("section", {
        has: page.getByRole("heading", { name: "Audit History" }),
      });
      await expect(auditHistory.getByText("Review created")).toBeVisible();
      await expect(auditHistory.getByText("Approved", { exact: true })).toBeVisible();
      await expect(auditHistory.getByText(/reviewer "e2e-slice3-reviewer"/)).toBeVisible();
    } finally {
      cleanupReviewIds(createdReviewIds);
    }
  });
});
