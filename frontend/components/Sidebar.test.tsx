import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { usePathnameMock } = vi.hoisted(() => ({ usePathnameMock: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: usePathnameMock }));

import { Sidebar } from "./Sidebar";

function renderSidebar(pathname: string) {
  usePathnameMock.mockReturnValue(pathname);
  return render(<Sidebar />);
}

describe("Sidebar active state", () => {
  it("marks System Overview active only at the exact root path", () => {
    renderSidebar("/");
    expect(screen.getByRole("link", { name: "System Overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Ask CareFlow" })).not.toHaveAttribute("aria-current");
  });

  it("marks Reviews active on the exact /reviews path", () => {
    renderSidebar("/reviews");
    expect(screen.getByRole("link", { name: "Reviews" })).toHaveAttribute("aria-current", "page");
  });

  it("marks Reviews active on a nested review detail path (Slice 7 fix)", () => {
    renderSidebar("/reviews/9fdd11a5-5469-4eaa-b2d1-06889a5e6255");
    expect(screen.getByRole("link", { name: "Reviews" })).toHaveAttribute("aria-current", "page");
    // No other nav item is ever active at the same time.
    expect(screen.getByRole("link", { name: "Evidence Workflow" })).not.toHaveAttribute("aria-current");
  });

  it("never treats every route as a match for System Overview's root path", () => {
    renderSidebar("/reviews/some-id");
    expect(screen.getByRole("link", { name: "System Overview" })).not.toHaveAttribute("aria-current");
  });

  it("renders Analytics as a disabled placeholder, never a fake functional link", () => {
    renderSidebar("/");
    expect(screen.queryByRole("link", { name: /Analytics/ })).not.toBeInTheDocument();
    const analytics = screen.getByText("Analytics").closest("[aria-disabled]");
    expect(analytics).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
  });

  it("exposes every functional nav item as a real, keyboard-reachable link", () => {
    renderSidebar("/");
    for (const label of [
      "System Overview",
      "Ask CareFlow",
      "Patient Data",
      "Claims",
      "CareFlow Assistant",
      "Evidence Workflow",
      "Reviews",
    ]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
  });
});
