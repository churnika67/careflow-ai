import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// A valid NEXT_PUBLIC_API_BASE_URL is required for every test run so
// lib/config.ts's validation never fails as a side effect of running
// unrelated tests. Individual tests that need a different value set it
// themselves before importing the module under test.
process.env.NEXT_PUBLIC_API_BASE_URL ??= "http://localhost:8000";

// React Testing Library does not auto-cleanup under Vitest without this --
// without it, each render() in a test file leaks into the next test's DOM.
afterEach(() => {
  cleanup();
});
