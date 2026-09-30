"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSystemStatusContext } from "./SystemStatusProvider";
import { isReviewSurfaceAllowed, reviewSurfaceBlockedReason } from "@/lib/reviewReadiness";
import { getReviewQueue, type ReviewApiErrorCategory } from "@/lib/api/reviewsApi";
import type { ReviewCase, ReviewStatus } from "@/lib/api/reviewTypes";
import { reviewStatusLabel, triggerReasonLabel } from "@/lib/reviewLabels";
import { workflowLabel } from "@/lib/workflowLabels";
import type { WorkflowDecision } from "@/lib/api/multiAgentTypes";
import { formatTimestamp } from "@/lib/formatting";
import structuredResultStyles from "./structured/StructuredResultStates.module.css";
import styles from "./ReviewQueue.module.css";

const STATUS_OPTIONS: { value: ReviewStatus | "all"; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "revision_requested", label: "Revision Requested" },
  { value: "all", label: "All statuses" },
];

const ERROR_MESSAGES: Record<ReviewApiErrorCategory, string> = {
  network: "CareFlow could not reach the backend. Check your connection and try again.",
  timeout: "The request took too long to complete. Please try again.",
  not_found: "The requested review data could not be found.",
  invalid: "This request could not be processed.",
  unexpected: "Something went wrong while loading the review queue. Please try again.",
};

type QueueState =
  | { status: "loading" }
  | { status: "ok"; reviews: ReviewCase[]; nextCursor: string | null }
  | { status: "error"; category: ReviewApiErrorCategory; requestId: string | null };

export function ReviewQueue() {
  const { status: systemStatus } = useSystemStatusContext();
  const [statusFilter, setStatusFilter] = useState<ReviewStatus | "all">("pending");
  // Cursor stack: cursorHistory[i] is the cursor that produced the CURRENT
  // page's data (null for the first page) -- lets "Previous" pop back to an
  // already-fetched page without the backend needing offset pagination.
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [state, setState] = useState<QueueState>({ status: "loading" });
  const abortRef = useRef<AbortController | null>(null);

  const surfaceAllowed = isReviewSurfaceAllowed(systemStatus);
  const blockedReason = reviewSurfaceBlockedReason(systemStatus);

  // No synchronous setState call in this function's own body -- only
  // inside the async .then() callback -- so it is safe to call directly
  // from the mount/dependency effect below (matching
  // hooks/useSystemStatus.ts's own established pattern exactly). Callers
  // that need an immediate "loading" state (the event handlers below) set
  // it themselves before triggering a reload, since that happens outside
  // an effect body.
  function load(cursor: string | null): void {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    getReviewQueue(
      {
        status: statusFilter === "all" ? undefined : statusFilter,
        cursor: cursor ?? undefined,
      },
      controller.signal,
    ).then((outcome) => {
      if (controller.signal.aborted) return;
      if (outcome.kind === "error") {
        setState({ status: "error", category: outcome.category, requestId: outcome.requestId });
        return;
      }
      setState({ status: "ok", reviews: outcome.page.reviews, nextCursor: outcome.page.next_cursor });
    });
  }

  useEffect(() => {
    if (!surfaceAllowed) return;
    load(cursorHistory[pageIndex]);
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surfaceAllowed, statusFilter, pageIndex]);

  function handleStatusFilterChange(next: ReviewStatus | "all") {
    setState({ status: "loading" });
    setStatusFilter(next);
    setCursorHistory([null]);
    setPageIndex(0);
  }

  function handleNext() {
    if (state.status !== "ok" || !state.nextCursor) return;
    const cursor = state.nextCursor;
    setState({ status: "loading" });
    setCursorHistory((prev) => {
      const next = prev.slice(0, pageIndex + 1);
      next.push(cursor);
      return next;
    });
    setPageIndex((prev) => prev + 1);
  }

  function handlePrevious() {
    if (pageIndex === 0) return;
    setState({ status: "loading" });
    setPageIndex((prev) => prev - 1);
  }

  function handleRefresh() {
    setState({ status: "loading" });
    load(cursorHistory[pageIndex]);
  }

  return (
    <div className={styles.page}>
      <section>
        <div className={styles.headingRow}>
          <span className={styles.headingIcon} aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12.5 10 17l9-10" />
            </svg>
          </span>
          <h1 className={styles.heading}>Reviews</h1>
        </div>
        <p className={styles.subheading}>
          CareFlow requests that were flagged for human review -- either because evidence validation
          found an issue, or because a reviewer explicitly requested review.
        </p>
      </section>

      <div className={styles.controls}>
        <label className={styles.filterLabel}>
          Status
          <select
            className={styles.filterSelect}
            value={statusFilter}
            onChange={(event) => handleStatusFilterChange(event.target.value as ReviewStatus | "all")}
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className={styles.refreshButton} onClick={handleRefresh} disabled={!surfaceAllowed}>
          Refresh
        </button>
      </div>

      {!surfaceAllowed && blockedReason && <p className={styles.blockedReason}>{blockedReason}</p>}

      {surfaceAllowed && (
        <div aria-live="polite">
          {state.status === "loading" && <p className={styles.loading}>Loading reviews…</p>}
          {state.status === "error" && (
            <div className={structuredResultStyles.error} role="alert">
              <p>{ERROR_MESSAGES[state.category]}</p>
              <button type="button" className={structuredResultStyles.retryButton} onClick={handleRefresh}>
                Retry
              </button>
              {state.requestId && (
                <p className={structuredResultStyles.technicalDetail}>Request ID: {state.requestId}</p>
              )}
            </div>
          )}
          {state.status === "ok" && state.reviews.length === 0 && (
            <p className={styles.empty} role="status">
              {statusFilter === "pending" ? "No pending reviews." : "No reviews found for this status."}
            </p>
          )}
          {state.status === "ok" && state.reviews.length > 0 && (
            <>
              <ul className={styles.list}>
                {state.reviews.map((review) => (
                  <li key={review.review_id} className={styles.card}>
                    <div className={styles.cardHeader}>
                      <span className={styles.statusBadge} data-status={review.status}>
                        {reviewStatusLabel(review.status)}
                      </span>
                      <span className={styles.workflow}>{workflowLabel(review.workflow as WorkflowDecision)}</span>
                    </div>
                    <p className={styles.triggerReasons}>
                      {review.trigger_reason_codes.map((code) => triggerReasonLabel(code)).join(" ")}
                    </p>
                    <p className={styles.meta}>
                      Created {formatTimestamp(review.created_at)} · Version {review.version}
                    </p>
                    <p className={styles.technicalDetail}>Review ID: {review.review_id}</p>
                    <Link href={`/reviews/${review.review_id}`} className={styles.viewLink}>
                      View review
                    </Link>
                  </li>
                ))}
              </ul>
              <div className={styles.pagination}>
                <button
                  type="button"
                  className={styles.pageButton}
                  onClick={handlePrevious}
                  disabled={pageIndex === 0}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className={styles.pageButton}
                  onClick={handleNext}
                  disabled={!state.nextCursor}
                >
                  Next
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
