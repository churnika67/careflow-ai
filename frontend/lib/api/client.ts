/**
 * A small typed wrapper around native fetch. No business logic lives
 * here -- endpoint-specific interpretation (e.g. "a 503 from /ready is
 * not an error, it's a valid degraded reading", or "a 502 from /query
 * with error.code=retrieval_unavailable means X") belongs in the caller,
 * see lib/api/systemStatus.ts and lib/api/policyQuery.ts.
 *
 * Responsibilities: base URL handling, request timeout/abort, JSON
 * parsing, and normalizing transport-level failures into ApiClientError.
 * A non-2xx HTTP status with a parseable JSON body is returned normally
 * (ok: false, status, data) rather than thrown -- see errors.ts.
 */

import { apiBaseUrl } from "@/lib/config";
import { ApiClientError } from "./errors";

const DEFAULT_TIMEOUT_MS = 5000;
const REQUEST_ID_HEADER = "X-Request-ID";

export interface ApiResponse<T> {
  data: T;
  status: number;
  ok: boolean;
  requestId: string | null;
}

interface RequestOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
}

async function request<T>(
  path: string,
  init: { method: "GET" | "POST"; body?: unknown },
  options?: RequestOptions,
): Promise<ApiResponse<T>> {
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // If the caller also supplied a signal (e.g. to cancel on unmount),
  // aborting either one aborts the request.
  const externalSignal = options?.signal;
  const onExternalAbort = () => controller.abort();
  externalSignal?.addEventListener("abort", onExternalAbort);

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      method: init.method,
      headers:
        init.body !== undefined
          ? { Accept: "application/json", "Content-Type": "application/json" }
          : { Accept: "application/json" },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") {
      throw new ApiClientError({
        category: "timeout",
        message: `Request to ${path} timed out after ${timeoutMs}ms.`,
      });
    }
    throw new ApiClientError({
      category: "network",
      message: `Could not reach the CareFlow backend at ${apiBaseUrl}.`,
    });
  } finally {
    clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }

  const requestId = response.headers.get(REQUEST_ID_HEADER);

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiClientError({
      category: "invalid_response",
      message: `Received a non-JSON response from ${path} (status ${response.status}).`,
      status: response.status,
      requestId,
    });
  }

  return { data: data as T, status: response.status, ok: response.ok, requestId };
}

export function apiGet<T>(path: string, options?: RequestOptions): Promise<ApiResponse<T>> {
  return request<T>(path, { method: "GET" }, options);
}

export function apiPost<T>(
  path: string,
  body: unknown,
  options?: RequestOptions,
): Promise<ApiResponse<T>> {
  return request<T>(path, { method: "POST", body }, options);
}
