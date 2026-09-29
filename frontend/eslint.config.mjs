import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Phase 16 Slice 3: Playwright's own generated output (present on
    // disk after any local E2E run) is not source code -- without this,
    // `npm run lint` scans the HTML report's bundled, minified trace
    // viewer assets as if they were this project's own TypeScript.
    "playwright-report/**",
    "test-results/**",
  ]),
  {
    // Phase 16 Slice 2: e2e/ is Playwright test code, not React -- its
    // fixture-composition `use(...)` callback (from @playwright/test) is
    // unrelated to React's `use()` hook, but eslint-config-next's
    // react-hooks rules can't tell the two apart by name alone and flag
    // every occurrence as a rules-of-hooks violation. Scoped off here
    // rather than disabled per-line, since it's a whole-directory
    // false-positive, not a real risk (there is no React tree under
    // test in a Playwright fixture file).
    files: ["e2e/**/*.ts"],
    rules: {
      "react-hooks/rules-of-hooks": "off",
    },
  },
]);

export default eslintConfig;
