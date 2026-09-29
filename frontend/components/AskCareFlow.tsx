"use client";

import { useEffect, useRef, useState } from "react";
import { useSystemStatusContext } from "./SystemStatusProvider";
import { isPolicySubmissionAllowed, policySubmissionBlockedReason } from "@/lib/policyReadiness";
import { queryPolicy, type PolicyErrorCategory } from "@/lib/api/policyQuery";
import { QUESTION_MAX_LENGTH, type RAGAnswer } from "@/lib/api/types";
import { PolicyAbstainedResult, PolicyAnswerResult } from "./policy/PolicyAnswer";
import structuredResultStyles from "./structured/StructuredResultStates.module.css";
import styles from "./AskCareFlow.module.css";

// Confirmed against the real, currently-indexed CMS corpus before being
// hardcoded here (see docs/phase14_frontend_design.md's "Example
// questions") -- not invented, and re-verify if the corpus ever changes.
const EXAMPLE_QUESTIONS = [
  "Does Medicare cover hospital beds?",
  "What is required for a power wheelchair?",
  "When can electric powered hospital bed adjustments be covered?",
  "What strength and postural stability must a beneficiary have to operate a POV/scooter?",
];

type QuestionState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "answered"; answer: RAGAnswer; requestId: string | null }
  | { status: "abstained"; answer: RAGAnswer; requestId: string | null }
  | { status: "error"; category: PolicyErrorCategory; requestId: string | null };

const ERROR_MESSAGES: Record<PolicyErrorCategory, string> = {
  network: "CareFlow could not reach the backend. Check your connection and try again.",
  timeout: "The request took too long to complete. Please try again.",
  retrieval_unavailable:
    "The Medicare policy search index is temporarily unavailable. Please try again shortly.",
  generation_unavailable:
    "CareFlow's answer generation is temporarily unavailable. Please try again shortly.",
  unexpected: "Something went wrong while processing your question. Please try again.",
};

function validateQuestion(raw: string): string | null {
  if (raw.trim().length === 0) return "Please enter a question.";
  if (raw.length > QUESTION_MAX_LENGTH) {
    return `Please shorten your question to ${QUESTION_MAX_LENGTH} characters or fewer.`;
  }
  return null;
}

export function AskCareFlow() {
  const { status: systemStatus } = useSystemStatusContext();
  const [question, setQuestion] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [state, setState] = useState<QuestionState>({ status: "idle" });
  const [lastSubmitted, setLastSubmitted] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const submissionAllowed = isPolicySubmissionAllowed(systemStatus);
  const blockedReason = policySubmissionBlockedReason(systemStatus);
  const isSubmitting = state.status === "submitting";

  async function submit(questionToSend: string) {
    if (isSubmitting) return; // never a duplicate in-flight submission
    const problem = validateQuestion(questionToSend);
    if (problem) {
      setValidationError(problem);
      return;
    }
    // Trimmed once validation passes -- the backend's StrictModel does not
    // strip whitespace itself (no str_strip_whitespace, strict=True), so a
    // stray leading/trailing space (e.g. from a paste) must not silently
    // change what's actually sent versus what the "Please enter a
    // question" check already treated as blank.
    const trimmedQuestion = questionToSend.trim();
    setValidationError(null);
    // New submission clears the previous result immediately, then shows
    // loading, then the new result -- avoids ever pairing a stale answer
    // with a different, newer question on screen.
    setState({ status: "submitting" });
    setLastSubmitted(trimmedQuestion);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const outcome = await queryPolicy(trimmedQuestion, controller.signal);
    if (controller.signal.aborted) return;

    if (outcome.kind === "answered" || outcome.kind === "abstained") {
      setState({ status: outcome.kind, answer: outcome.answer, requestId: outcome.requestId });
    } else {
      setState({ status: "error", category: outcome.category, requestId: outcome.requestId });
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    void submit(question);
  }

  function handleExampleClick(example: string) {
    setQuestion(example);
    setValidationError(null);
  }

  function handleRetry() {
    if (lastSubmitted) void submit(lastSubmitted);
  }

  return (
    <div className={styles.page}>
      <section>
        <h1 className={styles.heading}>Ask CareFlow</h1>
        <p className={styles.subheading}>Ask a question about Medicare policy.</p>
      </section>

      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        <label htmlFor="ask-careflow-question" className={styles.label}>
          Your question
        </label>
        <textarea
          id="ask-careflow-question"
          className={styles.textarea}
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value);
            if (validationError) setValidationError(null);
          }}
          rows={4}
          maxLength={QUESTION_MAX_LENGTH}
          aria-invalid={validationError ? "true" : undefined}
          aria-describedby={validationError ? "ask-careflow-validation" : undefined}
          disabled={isSubmitting}
        />
        {validationError && (
          <p id="ask-careflow-validation" className={styles.validationError} role="alert">
            {validationError}
          </p>
        )}

        <div className={styles.examples}>
          <span className={styles.examplesLabel}>Example questions:</span>
          {EXAMPLE_QUESTIONS.map((example) => (
            <button
              key={example}
              type="button"
              className={styles.exampleChip}
              onClick={() => handleExampleClick(example)}
              disabled={isSubmitting}
            >
              {example}
            </button>
          ))}
        </div>

        <div className={styles.submitRow}>
          <button type="submit" className={styles.submitButton} disabled={isSubmitting || !submissionAllowed}>
            {isSubmitting ? "Searching Medicare policy…" : "Ask CareFlow"}
          </button>
          {!submissionAllowed && blockedReason && (
            <span className={styles.blockedReason}>{blockedReason}</span>
          )}
        </div>
      </form>

      <div aria-live="polite">
        {state.status === "submitting" && (
          <p className={styles.searching}>Searching Medicare policy…</p>
        )}

        {state.status === "answered" && (
          <PolicyAnswerResult answer={state.answer.answer} citations={state.answer.citations} />
        )}

        {state.status === "abstained" && <PolicyAbstainedResult />}

        {state.status === "error" && (
          <ErrorResult
            category={state.category}
            requestId={state.requestId}
            onRetry={handleRetry}
          />
        )}
      </div>
    </div>
  );
}

function ErrorResult({
  category,
  requestId,
  onRetry,
}: {
  category: PolicyErrorCategory;
  requestId: string | null;
  onRetry: () => void;
}) {
  return (
    <div className={structuredResultStyles.error} role="alert">
      <p>{ERROR_MESSAGES[category]}</p>
      <button type="button" className={structuredResultStyles.retryButton} onClick={onRetry}>
        Retry
      </button>
      {requestId && <p className={structuredResultStyles.technicalDetail}>Request ID: {requestId}</p>}
    </div>
  );
}
