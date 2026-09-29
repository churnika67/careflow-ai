"use client";

import { useEffect, useRef, useState } from "react";
import { useSystemStatusContext } from "./SystemStatusProvider";
import { isReviewSurfaceAllowed, reviewSurfaceBlockedReason } from "@/lib/reviewReadiness";
import { decideReview, getReviewDetail, type ReviewApiErrorCategory } from "@/lib/api/reviewsApi";
import type { ReviewCase, ReviewDecisionType, ReviewEvent } from "@/lib/api/reviewTypes";
import { reviewDecisionLabel, reviewEventLabel, reviewStatusLabel, triggerReasonLabel } from "@/lib/reviewLabels";
import { workflowLabel } from "@/lib/workflowLabels";
import type { WorkflowDecision } from "@/lib/api/multiAgentTypes";
import { formatTimestamp } from "@/lib/formatting";
import { MultiAgentResultView } from "./workflow/MultiAgentResultView";
import structuredResultStyles from "./structured/StructuredResultStates.module.css";
import styles from "./ReviewDetail.module.css";

const ERROR_MESSAGES: Record<ReviewApiErrorCategory, string> = {
  network: "CareFlow could not reach the backend. Check your connection and try again.",
  timeout: "The request took too long to complete. Please try again.",
  not_found: "This review could not be found.",
  invalid: "This review identifier is not valid.",
  unexpected: "Something went wrong while loading this review. Please try again.",
};

type LoadState =
  | { status: "loading" }
  | { status: "ok"; case: ReviewCase; events: ReviewEvent[] }
  | { status: "not_found" }
  | { status: "error"; category: ReviewApiErrorCategory; requestId: string | null };

type DecisionUiState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "conflict"; current: ReviewCase }
  | { status: "error"; category: ReviewApiErrorCategory; requestId: string | null };

export function ReviewDetail({ reviewId }: { reviewId: string }) {
  const { status: systemStatus } = useSystemStatusContext();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reviewerId, setReviewerId] = useState("");
  const [reason, setReason] = useState("");
  const [reviewerIdError, setReviewerIdError] = useState<string | null>(null);
  const [decisionState, setDecisionState] = useState<DecisionUiState>({ status: "idle" });
  const [showSnapshotJson, setShowSnapshotJson] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const surfaceAllowed = isReviewSurfaceAllowed(systemStatus);
  const blockedReason = reviewSurfaceBlockedReason(systemStatus);

  // No synchronous setState call in this function's own body -- only
  // inside the async .then() callback -- so it is safe to call directly
  // from the mount/dependency effect below (matching
  // hooks/useSystemStatus.ts's own established pattern exactly). Callers
  // outside an effect body (the Retry/Refresh buttons, and the
  // post-decision reload) set the "loading" state themselves, or accept a
  // brief stale-data window, before calling this.
  function load(): void {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    getReviewDetail(reviewId, controller.signal).then((outcome) => {
      if (controller.signal.aborted) return;
      if (outcome.kind === "not_found") {
        setState({ status: "not_found" });
        return;
      }
      if (outcome.kind === "error") {
        setState({ status: "error", category: outcome.category, requestId: outcome.requestId });
        return;
      }
      setState({ status: "ok", case: outcome.detail.case, events: outcome.detail.events });
    });
  }

  useEffect(() => {
    if (!surfaceAllowed) return;
    load();
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surfaceAllowed, reviewId]);

  function handleReload() {
    setState({ status: "loading" });
    load();
  }

  async function handleDecision(decision: ReviewDecisionType) {
    if (state.status !== "ok" || decisionState.status === "submitting") return;
    if (reviewerId.trim().length === 0) {
      setReviewerIdError("Please enter a reviewer identifier.");
      return;
    }
    setReviewerIdError(null);
    setDecisionState({ status: "submitting" });

    // Trimmed once validation passes -- see PatientData.tsx's identical
    // rationale (the backend's StrictModel does not strip whitespace).
    const trimmedReason = reason.trim();
    const outcome = await decideReview(reviewId, {
      reviewer_id: reviewerId.trim(),
      decision,
      reason: trimmedReason.length > 0 ? trimmedReason : undefined,
      expected_version: state.case.version,
    });

    if (outcome.kind === "conflict") {
      // Immediately reflect the backend's own returned current state --
      // never overwritten, never silently retried. The user can Refresh
      // separately to also pull the current audit history.
      setState((prev) => (prev.status === "ok" ? { ...prev, case: outcome.current } : prev));
      setDecisionState({ status: "conflict", current: outcome.current });
      return;
    }
    if (outcome.kind === "not_found") {
      setDecisionState({ status: "error", category: "not_found", requestId: outcome.requestId });
      return;
    }
    if (outcome.kind === "error") {
      setDecisionState({ status: "error", category: outcome.category, requestId: outcome.requestId });
      return;
    }

    // Re-fetch the full detail (case + events) rather than reconstructing
    // the event locally -- always shows exactly what the backend recorded.
    setDecisionState({ status: "idle" });
    load();
  }

  if (!surfaceAllowed) {
    return (
      <div className={styles.page}>
        <h1 className={styles.heading}>Review</h1>
        {blockedReason && <p className={styles.blockedReason}>{blockedReason}</p>}
      </div>
    );
  }

  if (state.status === "loading") {
    return (
      <div className={styles.page}>
        <h1 className={styles.heading}>Review</h1>
        <p className={styles.loading}>Loading review…</p>
      </div>
    );
  }

  if (state.status === "not_found") {
    return (
      <div className={styles.page}>
        <h1 className={styles.heading}>Review</h1>
        <p className={styles.empty} role="status">
          No review was found for this ID.
        </p>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className={styles.page}>
        <h1 className={styles.heading}>Review</h1>
        <div className={structuredResultStyles.error} role="alert">
          <p>{ERROR_MESSAGES[state.category]}</p>
          <button type="button" className={structuredResultStyles.retryButton} onClick={handleReload}>
            Retry
          </button>
          {state.requestId && (
            <p className={structuredResultStyles.technicalDetail}>Request ID: {state.requestId}</p>
          )}
        </div>
      </div>
    );
  }

  const { case: reviewCase, events } = state;
  const isPending = reviewCase.status === "pending";

  return (
    <div className={styles.page}>
      <section>
        <div className={styles.headingRow}>
          <h1 className={styles.heading}>Review</h1>
          <span className={styles.statusBadge} data-status={reviewCase.status}>
            {reviewStatusLabel(reviewCase.status)}
          </span>
        </div>
        <p className={styles.technicalDetail}>Review ID: {reviewCase.review_id}</p>
      </section>

      <section>
        <h2 className={styles.sectionHeading}>Review Metadata</h2>
        <dl className={styles.metaFields}>
          <div className={styles.metaField}>
            <dt>Workflow</dt>
            <dd>{workflowLabel(reviewCase.workflow as WorkflowDecision)}</dd>
          </div>
          <div className={styles.metaField}>
            <dt>Version</dt>
            <dd>{reviewCase.version}</dd>
          </div>
          <div className={styles.metaField}>
            <dt>Created</dt>
            <dd>{formatTimestamp(reviewCase.created_at)}</dd>
          </div>
          <div className={styles.metaField}>
            <dt>Updated</dt>
            <dd>{formatTimestamp(reviewCase.updated_at)}</dd>
          </div>
          {reviewCase.previous_review_id && (
            <div className={styles.metaField}>
              <dt>Previous review</dt>
              <dd className={styles.technicalDetail}>{reviewCase.previous_review_id}</dd>
            </div>
          )}
        </dl>
        <p className={styles.triggerHeading}>Why this was flagged for review:</p>
        <ul className={styles.triggerList}>
          {reviewCase.trigger_reason_codes.map((code) => (
            <li key={code}>
              {triggerReasonLabel(code)} <span className={styles.technicalDetail}>({code})</span>
            </li>
          ))}
        </ul>
        <p className={styles.technicalDetail}>Evidence fingerprint: {reviewCase.evidence_fingerprint}</p>
      </section>

      <section>
        <h2 className={styles.sectionHeading}>Evidence Snapshot</h2>
        <p className={styles.snapshotNote}>
          This is the evidence exactly as it was captured when this review was created. It is never
          re-run, refreshed, or replaced with a current result.
        </p>
        <MultiAgentResultView response={reviewCase.evidence_snapshot} />
        <button
          type="button"
          className={styles.jsonToggle}
          onClick={() => setShowSnapshotJson((prev) => !prev)}
          aria-expanded={showSnapshotJson}
        >
          {showSnapshotJson ? "Hide raw snapshot JSON" : "Show raw snapshot JSON"}
        </button>
        {showSnapshotJson && (
          <pre className={styles.snapshotJson}>{JSON.stringify(reviewCase.evidence_snapshot, null, 2)}</pre>
        )}
      </section>

      <section>
        <h2 className={styles.sectionHeading}>Audit History</h2>
        <ol className={styles.eventList}>
          {events.map((event) => (
            <li key={event.event_id} className={styles.event}>
              <p className={styles.eventHeadline}>{reviewEventLabel(event.event_type)}</p>
              <p className={styles.eventMeta}>
                {formatTimestamp(event.created_at)} ·{" "}
                {event.actor_type === "reviewer" ? `reviewer "${event.actor_id}"` : "system"}
                {event.previous_status && ` · ${reviewStatusLabel(event.previous_status)} → ${reviewStatusLabel(event.new_status)}`}
              </p>
              {event.reason && <p className={styles.eventReason}>&ldquo;{event.reason}&rdquo;</p>}
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2 className={styles.sectionHeading}>Decision</h2>
        {!isPending && (
          <p className={styles.terminalNote} role="status">
            This review has already been decided ({reviewStatusLabel(reviewCase.status)}). No further
            decision can be made from this page.
          </p>
        )}
        {/* Outside the isPending gate deliberately: a 409 conflict updates
            reviewCase to its now-terminal server state (see handleDecision),
            which would otherwise hide this very notice the instant it
            appears. Always rendered so the user actually sees why. */}
        <div aria-live="polite">
          {decisionState.status === "submitting" && <p className={styles.loading}>Saving review decision…</p>}
          {decisionState.status === "conflict" && (
            <div className={styles.conflictNotice} role="alert">
              <p>
                This review changed before your decision was saved. Refresh the review to see its
                current state.
              </p>
              <button type="button" className={styles.refreshButton} onClick={handleReload}>
                Refresh
              </button>
            </div>
          )}
          {decisionState.status === "error" && (
            <div className={structuredResultStyles.error} role="alert">
              <p>{ERROR_MESSAGES[decisionState.category]}</p>
              {decisionState.requestId && (
                <p className={structuredResultStyles.technicalDetail}>Request ID: {decisionState.requestId}</p>
              )}
            </div>
          )}
        </div>
        {isPending && (
          <div className={styles.decisionForm}>
            <fieldset className={styles.fieldset}>
              <legend className={styles.legend}>Reviewer identifier</legend>
              <input
                id="review-reviewer-id"
                aria-label="Reviewer identifier"
                type="text"
                className={styles.input}
                value={reviewerId}
                onChange={(event) => {
                  setReviewerId(event.target.value);
                  if (reviewerIdError) setReviewerIdError(null);
                }}
                disabled={decisionState.status === "submitting"}
                aria-invalid={reviewerIdError ? "true" : undefined}
                aria-describedby="review-reviewer-id-hint"
              />
              <p id="review-reviewer-id-hint" className={styles.hint}>
                Used for application audit history.
              </p>
              {reviewerIdError && (
                <p className={styles.validationError} role="alert">
                  {reviewerIdError}
                </p>
              )}
            </fieldset>

            <fieldset className={styles.fieldset}>
              <legend className={styles.legend}>Reason (optional)</legend>
              <textarea
                id="review-reason"
                aria-label="Reason"
                className={styles.textarea}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={2}
                maxLength={2000}
                disabled={decisionState.status === "submitting"}
              />
            </fieldset>

            <p className={styles.approvalDisclaimer}>
              Approval accepts this CareFlow output for the application workflow. It is not a
              coverage, eligibility, medical-necessity, claim, or clinical decision.
            </p>

            <div className={styles.decisionButtons}>
              <button
                type="button"
                className={styles.approveButton}
                onClick={() => void handleDecision("approve")}
                disabled={decisionState.status === "submitting"}
              >
                {reviewDecisionLabel("approve")}
              </button>
              <button
                type="button"
                className={styles.rejectButton}
                onClick={() => void handleDecision("reject")}
                disabled={decisionState.status === "submitting"}
              >
                {reviewDecisionLabel("reject")}
              </button>
              <button
                type="button"
                className={styles.revisionButton}
                onClick={() => void handleDecision("request_revision")}
                disabled={decisionState.status === "submitting"}
              >
                {reviewDecisionLabel("request_revision")}
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
