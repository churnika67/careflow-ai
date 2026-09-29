import { expect, test } from "./fixtures";
import { KNOWN_POLICY_QUESTION } from "./fixtures";

/**
 * E2E-2: policy question -> evidence/citation UI.
 *
 * Uses a real, committed, exact_lexical-category golden question
 * (Hit@1=1.0 across every retrieval mode per the Phase 12 audit) --
 * never an invented question. Asserts evidence/citation semantics, not
 * exact generated prose (the deterministic provider's exact wording is
 * an implementation detail this journey does not pin down further than
 * "a real citation for the real expected chunk is present").
 */
test.describe("E2E-2: policy question journey", () => {
  test("submitting a real policy question renders an answer with a real citation", async ({ page }) => {
    await page.goto("/ask");
    await expect(page.getByRole("heading", { name: /ask careflow/i })).toBeVisible();

    const submit = page.getByRole("button", { name: "Ask CareFlow" });
    await expect(submit).toBeEnabled();

    await page.getByLabel("Your question").fill(KNOWN_POLICY_QUESTION);
    await submit.click();

    // Real backend round trip -- no mocked/intercepted response.
    await expect(page.getByText("Citation 1")).toBeVisible({ timeout: 15_000 });

    // Evidence/citation semantics, not exact generated prose: the real
    // expected chunk's own document title/section must appear somewhere
    // in the rendered evidence, proving the correct chunk was cited.
    await expect(page.getByText(/home use of oxygen/i)).toBeVisible();

    // Never rendered as an error or an insufficient-evidence abstention.
    await expect(page.getByText(/could not reach the backend/i)).not.toBeVisible();
    await expect(page.getByText(/insufficient evidence/i)).not.toBeVisible();
  });
});
