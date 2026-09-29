/**
 * Frontend environment configuration.
 *
 * The only server/browser-shared value this app needs is the CareFlow
 * backend's base URL. It is never hard-coded here -- see
 * docs/phase14_frontend_design.md's "API base URL strategy" -- and this
 * module never reads or re-exports any other `process.env` value, so no
 * server-only secret can accidentally reach a client bundle through it.
 */

function readApiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL;

  if (!raw || raw.trim() === "") {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL is not set. Copy frontend/.env.example to " +
        "frontend/.env.local and set it to your running CareFlow backend's " +
        "base URL (for example http://localhost:8000).",
    );
  }

  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error(
      `NEXT_PUBLIC_API_BASE_URL is not a valid URL: "${raw}". It must be an ` +
        "absolute URL such as http://localhost:8000.",
    );
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(
      `NEXT_PUBLIC_API_BASE_URL must use http or https, got "${parsed.protocol}" in "${raw}".`,
    );
  }

  // Normalized without a trailing slash so callers can safely do
  // `${apiBaseUrl}/live` without producing a double slash.
  return raw.replace(/\/+$/, "");
}

export const apiBaseUrl = readApiBaseUrl();
