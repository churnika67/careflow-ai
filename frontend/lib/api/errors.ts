/**
 * Bounded API error model. Only transport-level failures (network,
 * timeout, an unparseable response body) become an ApiClientError -- a
 * non-2xx HTTP response with a valid JSON body is NOT automatically an
 * error, since some backend endpoints (GET /ready's 503) return a
 * meaningful, well-typed body precisely when the status is non-2xx. See
 * lib/api/client.ts and lib/api/systemStatus.ts for how that distinction
 * is used.
 *
 * Never carries a backend stack trace, raw exception body, credential, or
 * internal URL -- only a bounded category, an optional HTTP status, a
 * short operator-safe message, and an optional request ID.
 */

export type ApiErrorCategory = "network" | "timeout" | "invalid_response";

export class ApiClientError extends Error {
  readonly category: ApiErrorCategory;
  readonly status?: number;
  readonly requestId?: string;

  constructor(init: {
    category: ApiErrorCategory;
    message: string;
    status?: number;
    requestId?: string | null;
  }) {
    super(init.message);
    this.name = "ApiClientError";
    this.category = init.category;
    this.status = init.status;
    this.requestId = init.requestId ?? undefined;
  }
}
