import { expect, test } from "./fixtures";

/**
 * E2E-9 (bounded, optional): an unrelated free-text request abstains
 * gracefully instead of being force-routed to policy or structured data.
 *
 * Reuses real, already-proven backend behavior
 * (tests/test_orchestration_api.py::test_unrelated_question_abstains_with_200
 * -- "what is the weather" -> route=abstain, status=abstained,
 * abstention_reason=unsupported_request) -- never an invented failure
 * mode, and never a forced OpenAI failure.
 */
test.describe("E2E-9: abstention journey", () => {
  test("an unrelated free-text request abstains instead of guessing a route", async ({ page }) => {
    await page.goto("/assistant");
    await expect(page.getByRole("heading", { name: /careflow assistant/i })).toBeVisible();

    const submit = page.getByRole("button", { name: "Ask CareFlow" });
    await expect(submit).toBeEnabled();

    await page.getByLabel("Your request").fill("what is the weather");
    await submit.click();

    await expect(page.getByText("CareFlow could not process this structured data request.")).toBeVisible({
      timeout: 15_000,
    });

    // Never silently rendered as a policy answer, a structured record, or
    // a generic error -- an abstention, specifically.
    await expect(page.getByText("Citation 1")).not.toBeVisible();
    await expect(page.getByText(/could not reach the backend/i)).not.toBeVisible();
  });
});
