import { execFileSync } from "node:child_process";
import path from "node:path";

/**
 * Phase 16 Slice 3 (E2E-7): deletes review rows this E2E run created,
 * mirroring -- never reimplementing -- tests/test_review_api.py's
 * `created_review_ids` fixture. That fixture's cleanup logic is Python
 * (delete review_events, then review_cases in reverse creation order, via
 * the project's own async Postgres connection helper); a Playwright test
 * runs in Node, so this shells out once to
 * scripts/cleanup_review_ids.py -- the exact same logic, factored out to
 * run standalone -- rather than re-implementing the SQL a second time in
 * TypeScript.
 *
 * The developer stack's baseline 4 review_cases / 8 review_events are
 * never touched: only the review_ids this test itself created and
 * tracked are ever passed here.
 *
 * Python interpreter resolution: defaults to the local convention
 * (`.venv/bin/python`, per README's "Native backend development" setup)
 * but is overridable via PYTHON_BIN -- CI (Phase 16 Slice 4) installs
 * dependencies directly onto the runner's Python via actions/setup-python
 * rather than creating a project-local .venv, and sets PYTHON_BIN=python
 * accordingly. Never hard-code a second, CI-specific path here.
 */
export function cleanupReviewIds(reviewIds: string[]): void {
  if (reviewIds.length === 0) return;
  const repoRoot = path.resolve(__dirname, "..", "..");
  const pythonBin = process.env.PYTHON_BIN ?? path.join(repoRoot, ".venv", "bin", "python");
  execFileSync(pythonBin, ["scripts/cleanup_review_ids.py", ...reviewIds], {
    cwd: repoRoot,
    stdio: "pipe",
  });
}
