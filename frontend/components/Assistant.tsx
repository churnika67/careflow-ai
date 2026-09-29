"use client";

import { useEffect, useRef, useState } from "react";
import { useSystemStatusContext } from "./SystemStatusProvider";
import { isAssistantSubmissionAllowed, assistantSubmissionBlockedReason } from "@/lib/assistantReadiness";
import { orchestrateQuestion, type OrchestrateErrorCategory } from "@/lib/api/orchestrateQuery";
import type { OrchestrationResponse } from "@/lib/api/orchestrationTypes";
import { routeLabel, toolLabel } from "@/lib/routingLabels";
import { PolicyAbstainedResult, PolicyAnswerResult } from "./policy/PolicyAnswer";
import { DatasetBadge } from "./structured/DatasetBadge";
import { SyntheticDataNotice } from "./structured/SyntheticDataNotice";
import { RecordCard } from "./structured/RecordCard";
import { RecordFields } from "./structured/RecordFields";
import { GenericRecordFields } from "./structured/GenericRecordFields";
import { StructuredAbstention } from "./structured/StructuredResultStates";
import { PATIENT_SUMMARY_FIELDS, BENEFICIARY_IDENTITY_FIELDS } from "./structured/fieldSpecs";
import styles from "./Assistant.module.css";
import structuredResultStyles from "./structured/StructuredResultStates.module.css";

const QUESTION_MAX_LENGTH = 4000;

// Verified against the real running router (see docs/phase14_frontend_
// design.md's "Example requests" table): each routes exactly as shown
// here -- policy, fhir/get_patient_summary, synpuf/get_beneficiary_summary.
// An unsupported or cross-dataset-linkage phrasing is deliberately never
// offered as a clickable example (Slice 4's own instruction), even though
// both are exercised directly against the live backend in this slice's
// own verification.
const EXAMPLE_REQUESTS = [
  { label: "Medicare Policy", text: "What does Medicare say about hospital beds?" },
  {
    label: "Synthetic FHIR",
    text: "Show me FHIR patient 31a2e8ec-69fc-8a71-3ab6-36cbdd508713",
  },
  {
    label: "Synthetic Claims",
    text: "Look up SynPUF beneficiary 00013D2EFD8E45D1",
  },
];

type AssistantState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "result"; response: OrchestrationResponse; requestId: string | null }
  | { status: "abstained"; response: OrchestrationResponse; requestId: string | null }
  | { status: "error"; category: OrchestrateErrorCategory; requestId: string | null };

const ERROR_MESSAGES: Record<OrchestrateErrorCategory, string> = {
  network: "CareFlow could not reach the backend. Check your connection and try again.",
  timeout: "The request took too long to complete. Please try again.",
  orchestration_unavailable: "CareFlow's routing service is temporarily unavailable. Please try again shortly.",
  retrieval_unavailable:
    "The Medicare policy search index is temporarily unavailable. Please try again shortly.",
  unexpected: "Something went wrong while processing your request. Please try again.",
};

function validateQuestion(raw: string): string | null {
  if (raw.trim().length === 0) return "Please enter a request.";
  if (raw.length > QUESTION_MAX_LENGTH) {
    return `Please shorten your request to ${QUESTION_MAX_LENGTH} characters or fewer.`;
  }
  return null;
}

export function Assistant() {
  const { status: systemStatus } = useSystemStatusContext();
  const [question, setQuestion] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [state, setState] = useState<AssistantState>({ status: "idle" });
  const [lastSubmitted, setLastSubmitted] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const submissionAllowed = isAssistantSubmissionAllowed(systemStatus);
  const blockedReason = assistantSubmissionBlockedReason(systemStatus);
  const isSubmitting = state.status === "submitting";

  async function submit(questionToSend: string) {
    if (isSubmitting) return;
    const problem = validateQuestion(questionToSend);
    if (problem) {
      setValidationError(problem);
      return;
    }
    // Trimmed once validation passes -- the backend's StrictModel does not
    // strip whitespace itself (no str_strip_whitespace, strict=True), and
    // the router is phrasing-sensitive, so a stray leading/trailing space
    // must not silently change what's actually classified.
    const trimmedQuestion = questionToSend.trim();
    setValidationError(null);
    setState({ status: "submitting" });
    setLastSubmitted(trimmedQuestion);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const outcome = await orchestrateQuestion(trimmedQuestion, controller.signal);
    if (controller.signal.aborted) return;

    if (outcome.kind === "error") {
      setState({ status: "error", category: outcome.category, requestId: outcome.requestId });
      return;
    }
    if (outcome.response.status === "abstained") {
      setState({ status: "abstained", response: outcome.response, requestId: outcome.requestId });
    } else {
      setState({ status: "result", response: outcome.response, requestId: outcome.requestId });
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    void submit(question);
  }

  function handleExampleClick(text: string) {
    setQuestion(text);
    setValidationError(null);
  }

  function handleRetry() {
    if (lastSubmitted) void submit(lastSubmitted);
  }

  return (
    <div className={styles.page}>
      <section>
        <h1 className={styles.heading}>CareFlow Assistant</h1>
        <p className={styles.subheading}>
          Ask CareFlow to find information from supported healthcare sources.
        </p>
        <p className={styles.routerNote}>
          CareFlow routes supported requests to the appropriate healthcare information source.
          It does not reason about medical questions outside of the sources below.
        </p>
        <ul className={styles.sourceList}>
          <li>Medicare Policy</li>
          <li>Synthetic FHIR Patient Data</li>
          <li>Synthetic Claims</li>
        </ul>
      </section>

      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        <label htmlFor="assistant-question" className={styles.label}>
          Your request
        </label>
        <textarea
          id="assistant-question"
          className={styles.textarea}
          value={question}
          onChange={(event) => {
            setQuestion(event.target.value);
            if (validationError) setValidationError(null);
          }}
          rows={4}
          maxLength={QUESTION_MAX_LENGTH}
          aria-invalid={validationError ? "true" : undefined}
          aria-describedby={validationError ? "assistant-validation" : undefined}
          disabled={isSubmitting}
        />
        {validationError && (
          <p id="assistant-validation" className={styles.validationError} role="alert">
            {validationError}
          </p>
        )}

        <div className={styles.examples}>
          <span className={styles.examplesLabel}>Example requests:</span>
          {EXAMPLE_REQUESTS.map((example) => (
            <button
              key={example.text}
              type="button"
              className={styles.exampleChip}
              onClick={() => handleExampleClick(example.text)}
              disabled={isSubmitting}
            >
              {example.text}
            </button>
          ))}
        </div>

        <div className={styles.submitRow}>
          <button type="submit" className={styles.submitButton} disabled={isSubmitting || !submissionAllowed}>
            {isSubmitting ? "Routing your request…" : "Ask CareFlow"}
          </button>
          {!submissionAllowed && blockedReason && (
            <span className={styles.blockedReason}>{blockedReason}</span>
          )}
        </div>
      </form>

      <div aria-live="polite">
        {state.status === "submitting" && <p className={styles.routing}>Routing your request…</p>}

        {state.status === "result" && <RoutedResult response={state.response} />}

        {state.status === "abstained" && <RoutedAbstention response={state.response} />}

        {state.status === "error" && (
          <ErrorResult category={state.category} requestId={state.requestId} onRetry={handleRetry} />
        )}
      </div>
    </div>
  );
}

function RoutingSummary({ response }: { response: OrchestrationResponse }) {
  return (
    <div className={styles.routingSummary}>
      <p className={styles.routingSummaryLabel}>CareFlow Routing</p>
      <p>Source: {routeLabel(response.route)}</p>
      {response.tool && (
        <p>
          Tool: {toolLabel(response.tool)}{" "}
          <span className={styles.technicalDetail}>({response.tool})</span>
        </p>
      )}
    </div>
  );
}

function RoutedResult({ response }: { response: OrchestrationResponse }) {
  return (
    <div className={styles.result}>
      <RoutingSummary response={response} />
      {response.route === "policy" && (
        <PolicyAnswerResult answer={response.answer ?? ""} citations={response.citations ?? []} />
      )}
      {response.route === "fhir" && <StructuredResult response={response} kind="fhir" />}
      {response.route === "synpuf" && <StructuredResult response={response} kind="synpuf" />}
    </div>
  );
}

function StructuredResult({
  response,
  kind,
}: {
  response: OrchestrationResponse;
  kind: "fhir" | "synpuf";
}) {
  const data = response.data as Record<string, unknown> | null;
  const defaultTool = kind === "fhir" ? "get_patient_summary" : "get_beneficiary_summary";
  const fields = kind === "fhir" ? PATIENT_SUMMARY_FIELDS : BENEFICIARY_IDENTITY_FIELDS;

  return (
    <div className={styles.structuredResult}>
      <DatasetBadge name={kind === "fhir" ? "Synthea FHIR" : "CMS DE-SynPUF"} />
      <SyntheticDataNotice>
        {kind === "fhir"
          ? "These records are generated synthetic healthcare data and do not represent real patients."
          : "These records are synthetic, de-identified demonstration claims data and do not represent real Medicare beneficiaries."}
      </SyntheticDataNotice>
      {response.record_count !== null && (
        <p className={styles.recordCount}>
          {response.record_count} record{response.record_count === 1 ? "" : "s"}
        </p>
      )}
      {data && (
        <RecordCard>
          {response.tool === defaultTool ? (
            <RecordFields record={data} fields={fields} />
          ) : (
            // The smallest generic safe renderer for a shape this page has
            // no dedicated FieldSpec[] for -- never reachable from natural-
            // language routing today (which always resolves to the default
            // tool), kept as a deliberate defensive fallback.
            <GenericRecordFields record={data} />
          )}
        </RecordCard>
      )}
    </div>
  );
}

function RoutedAbstention({ response }: { response: OrchestrationResponse }) {
  const reason = response.abstention_reason ?? "unsupported_request";
  return (
    <div className={styles.result}>
      <RoutingSummary response={response} />
      {reason === "policy_abstained" ? (
        <PolicyAbstainedResult />
      ) : reason === "cross_dataset_linkage_request" ? (
        <div className={styles.crossDatasetNotice} role="status">
          <p>
            CareFlow does not link identities across the synthetic FHIR and SynPUF datasets.
          </p>
        </div>
      ) : (
        <StructuredAbstention reason={reason} />
      )}
    </div>
  );
}

// Deliberately not structured/StructuredResultStates.tsx's <StructuredError>
// component directly: its error-category union (StructuredErrorCategory)
// doesn't match OrchestrateErrorCategory (this page's requests can fail for
// either a policy- or a structured-route reason, so it has its own
// "retrieval_unavailable"/"orchestration_unavailable" categories). Reuses
// that component's CSS classes directly, though, so the visual treatment
// is identical without a second copy of the styles.
function ErrorResult({
  category,
  requestId,
  onRetry,
}: {
  category: OrchestrateErrorCategory;
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
