import { expect, test } from "./fixtures";

/**
 * E2E-1: application + readiness smoke.
 *
 * Proves the application loads, every primary Sidebar destination is
 * reachable, and backend-dependent status is healthy -- not an
 * exhaustive click-every-control test, a smoke journey only.
 */
test.describe("E2E-1: application smoke", () => {
  test("loads, shows a healthy status, and every primary Sidebar destination is reachable", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "CareFlow AI" })).toBeVisible();
    // The header's live/ready status badge -- healthy stack, never "unavailable".
    await expect(page.getByText("Ready")).toBeVisible();

    const destinations: { label: string; href: string; heading: string | RegExp }[] = [
      { label: "System Overview", href: "/", heading: "CareFlow AI" },
      { label: "Ask CareFlow", href: "/ask", heading: /ask careflow/i },
      { label: "Patient Data", href: "/patient-data", heading: /patient data/i },
      { label: "Claims", href: "/claims", heading: /claims/i },
      { label: "CareFlow Assistant", href: "/assistant", heading: /careflow assistant/i },
      { label: "Evidence Workflow", href: "/workflow", heading: /evidence workflow/i },
      { label: "Reviews", href: "/reviews", heading: /reviews/i },
      { label: "Analytics", href: "/analytics", heading: /analytics/i },
    ];

    for (const destination of destinations) {
      await page.getByRole("link", { name: destination.label }).click();
      await expect(page).toHaveURL(new RegExp(`${destination.href.replace("/", "\\/")}$`));
      await expect(page.getByRole("heading", { name: destination.heading }).first()).toBeVisible();
      // No page under a healthy stack should ever show the generic
      // "backend is currently unavailable" message.
      await expect(page.getByText(/backend is currently unavailable/i)).not.toBeVisible();
    }
  });
});
