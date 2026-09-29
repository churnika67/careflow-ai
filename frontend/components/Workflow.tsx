"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSystemStatusContext } from "./SystemStatusProvider";
import { isWorkflowSubmissionAllowed, workflowSubmissionBlockedReason } from "@/lib/workflowReadiness";
import {
  runReviewableCombinedWorkflow,
  type ReviewableQueryErrorCategory,
} from "@/lib/api/reviewableQuery";
import type { ReviewableQueryResponse } from "@/lib/api/reviewTypes";
import { reviewStatusLabel, triggerReasonLabel } from "@/lib/reviewLabels";
import type { Route } from "@/lib/api/orchestrationTypes";
import { QUESTION_MAX_LENGTH } from "@/lib/api/types";
import { toolLabel } from "@/lib/routingLabels";
import { MultiAgentResultView } from "./workflow/MultiAgentResultView";
import type { WorkflowStructuredTool } from "./structured/ToolResultView";
import structuredResultStyles from "./structured/StructuredResultStates.module.css";
import styles from "./Workflow.module.css";

// Queried directly from the live database in earlier slices (see
// docs/phase14_frontend_design.md's "Demo synthetic IDs") and re-verified
// against the real POST /multi-agent endpoint in Slice 5 -- see the "Real
// Policy + FHIR/SynPUF verification" sections of the design doc.
const EXAMPLE_FHIR_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713";
const EXAMPLE_SYNPUF_BENEFICIARY_ID = "00013D2EFD8E45D1";
const EXAMPLE_POLICY_QUESTION = "What does Medicare say about hospital beds?";

type StructuredDataset = "fhir" | "synpuf";

interface ToolOption {
  tool: WorkflowStructuredTool;
  label: string;
}

// Only the identifier-scoped tools -- the population-level aggregate tools
// and get_claim_details (which needs a claim_row_id, not a patient/
// beneficiary identifier) are out of scope for this single-identifier form.
// See components/structured/ToolResultView.tsx's own module comment.
const FHIR_TOOLS: ToolOption[] = [
  "get_patient_summary",
  "get_patient_encounters",
  "get_patient_conditions",
  "get_patient_procedures",
  "get_patient_observations",
  "get_patient_medication_requests",
].map((tool) => ({ tool: tool as WorkflowStructuredTool, label: toolLabel(tool) }));

const SYNPUF_TOOLS: ToolOption[] = ["get_beneficiary_summary", "get_claims_for_beneficiary"].map((tool) => ({
  tool: tool as WorkflowStructuredTool,
  label: toolLabel(tool),
}));

function toolsFor(dataset: StructuredDataset): ToolOption[] {
  return dataset === "fhir" ? FHIR_TOOLS : SYNPUF_TOOLS;
}

function defaultToolFor(dataset: StructuredDataset): WorkflowStructuredTool {
  return dataset === "fhir" ? "get_patient_summary" : "get_beneficiary_summary";
}

function identifierLabelFor(dataset: StructuredDataset): string {
  return dataset === "fhir" ? "Synthetic Patient ID" : "Synthetic Beneficiary ID";
}

function toolArgumentsFor(dataset: StructuredDataset, identifier: string): Record<string, unknown> {
  return dataset === "fhir" ? { patient_id: identifier } : { beneficiary_id: identifier };
}

interface FormErrors {
  policyQuestion?: string;
  identifier?: string;
}

function validateForm(policyQuestion: string, identifier: string): FormErrors {
  const errors: FormErrors = {};
  if (policyQuestion.trim().length === 0) {
    errors.policyQuestion = "Please enter a Medicare policy question.";
  } else if (policyQuestion.length > QUESTION_MAX_LENGTH) {
    errors.policyQuestion = `Please shorten the policy question to ${QUESTION_MAX_LENGTH} characters or fewer.`;
  }
  if (identifier.trim().length === 0) {
    errors.identifier = "Please enter a synthetic identifier.";
  }
  return errors;
}

type WorkflowState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "result"; response: ReviewableQueryResponse; requestId: string | null }
  | { status: "error"; category: ReviewableQueryErrorCategory; requestId: string | null };

const ERROR_MESSAGES: Record<ReviewableQueryErrorCategory, string> = {
  network: "CareFlow could not reach the backend. Check your connection and try again.",
  timeout: "The request took too long to complete. Please try again.",
  retrieval_unavailable: "The Medicare policy search index is temporarily unavailable. Please try again shortly.",
  workflow_unavailable: "The evidence workflow service is temporarily unavailable. Please try again shortly.",
  unexpected: "Something went wrong while processing this request. Please try again.",
};

interface SubmitInput {
  policyQuestion: string;
  dataset: StructuredDataset;
  tool: WorkflowStructuredTool;
  identifier: string;
  requestReview: boolean;
}

export function Workflow() {
  const { status: systemStatus } = useSystemStatusContext();
  const [policyQuestion, setPolicyQuestion] = useState("");
  const [dataset, setDataset] = useState<StructuredDataset>("fhir");
  const [tool, setTool] = useState<WorkflowStructuredTool>("get_patient_summary");
  const [identifier, setIdentifier] = useState("");
  const [requestReview, setRequestReview] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [state, setState] = useState<WorkflowState>({ status: "idle" });
  const [lastSubmitted, setLastSubmitted] = useState<SubmitInput | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const submissionAllowed = isWorkflowSubmissionAllowed(systemStatus);
  const blockedReason = workflowSubmissionBlockedReason(systemStatus);
  const isSubmitting = state.status === "submitting";

  async function submit(input: SubmitInput) {
    if (isSubmitting) return;
    setState({ status: "submitting" });
    setLastSubmitted(input);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const outcome = await runReviewableCombinedWorkflow(
      {
        policyQuestion: input.policyQuestion,
        structuredRoute: input.dataset as Route,
        tool: input.tool,
        toolArguments: toolArgumentsFor(input.dataset, input.identifier),
        explicitReviewRequested: input.requestReview,
      },
      controller.signal,
    );
    if (controller.signal.aborted) return;

    if (outcome.kind === "error") {
      setState({ status: "error", category: outcome.category, requestId: outcome.requestId });
      return;
    }
    setState({ status: "result", response: outcome.response, requestId: outcome.requestId });
  }

  function handleDatasetChange(next: StructuredDataset) {
    if (next === dataset) return;
    setDataset(next);
    setTool(defaultToolFor(next));
    // Switching dataset never carries the old identifier forward -- a FHIR
    // patient ID and a SynPUF beneficiary ID are never interchangeable (see
    // docs/phase14_frontend_design.md's Slice 5 "Dataset boundary").
    setIdentifier("");
    setErrors((prev) => ({ ...prev, identifier: undefined }));
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const problems = validateForm(policyQuestion, identifier);
    if (Object.keys(problems).length > 0) {
      setErrors(problems);
      return;
    }
    // Trimmed once validation passes -- see PatientData.tsx's identical
    // rationale (the backend's StrictModel does not strip whitespace).
    setErrors({});
    void submit({
      policyQuestion: policyQuestion.trim(),
      dataset,
      tool,
      identifier: identifier.trim(),
      requestReview,
    });
  }

  function handleRetry() {
    if (lastSubmitted) void submit(lastSubmitted);
  }

  function loadExample(exampleDataset: StructuredDataset) {
    const exampleIdentifier = exampleDataset === "fhir" ? EXAMPLE_FHIR_PATIENT_ID : EXAMPLE_SYNPUF_BENEFICIARY_ID;
    setPolicyQuestion(EXAMPLE_POLICY_QUESTION);
    setDataset(exampleDataset);
    setTool(defaultToolFor(exampleDataset));
    setIdentifier(exampleIdentifier);
    setErrors({});
  }

  return (
    <div className={styles.page}>
      <section>
        <h1 className={styles.heading}>Evidence Workflow</h1>
        <p className={styles.subheading}>
          Run a CareFlow coordinated workflow that gathers Medicare policy evidence and synthetic
          healthcare data for one request, then validates the result.
        </p>
        <p className={styles.disclaimerNote}>
          Policy evidence and synthetic healthcare data are independent evidence sources. Running
          them together does not determine coverage, eligibility, medical necessity, or claim
          approval.
        </p>
      </section>

      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>Policy question</legend>
          <textarea
            id="workflow-policy-question"
            aria-label="Policy question"
            className={styles.textarea}
            value={policyQuestion}
            onChange={(event) => {
              setPolicyQuestion(event.target.value);
              if (errors.policyQuestion) setErrors((prev) => ({ ...prev, policyQuestion: undefined }));
            }}
            rows={3}
            maxLength={QUESTION_MAX_LENGTH}
            disabled={isSubmitting}
            aria-invalid={errors.policyQuestion ? "true" : undefined}
            aria-describedby={errors.policyQuestion ? "workflow-policy-question-error" : undefined}
          />
          {errors.policyQuestion && (
            <p id="workflow-policy-question-error" className={styles.validationError} role="alert">
              {errors.policyQuestion}
            </p>
          )}
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>Structured source</legend>
          <div className={styles.radioRow}>
            <label className={styles.radioLabel}>
              <input
                type="radio"
                name="workflow-dataset"
                value="fhir"
                checked={dataset === "fhir"}
                onChange={() => handleDatasetChange("fhir")}
                disabled={isSubmitting}
              />
              Synthetic FHIR
            </label>
            <label className={styles.radioLabel}>
              <input
                type="radio"
                name="workflow-dataset"
                value="synpuf"
                checked={dataset === "synpuf"}
                onChange={() => handleDatasetChange("synpuf")}
                disabled={isSubmitting}
              />
              Synthetic Claims
            </label>
          </div>
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>{identifierLabelFor(dataset)}</legend>
          <input
            id="workflow-identifier"
            aria-label={identifierLabelFor(dataset)}
            type="text"
            className={styles.input}
            value={identifier}
            onChange={(event) => {
              setIdentifier(event.target.value);
              if (errors.identifier) setErrors((prev) => ({ ...prev, identifier: undefined }));
            }}
            disabled={isSubmitting}
            aria-invalid={errors.identifier ? "true" : undefined}
            aria-describedby={errors.identifier ? "workflow-identifier-error" : undefined}
          />
          {errors.identifier && (
            <p id="workflow-identifier-error" className={styles.validationError} role="alert">
              {errors.identifier}
            </p>
          )}
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>Structured information</legend>
          <select
            id="workflow-tool"
            aria-label="Structured information"
            className={styles.select}
            value={tool}
            onChange={(event) => setTool(event.target.value as WorkflowStructuredTool)}
            disabled={isSubmitting}
          >
            {toolsFor(dataset).map((option) => (
              <option key={option.tool} value={option.tool}>
                {option.label}
              </option>
            ))}
          </select>
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>Human review</legend>
          <label className={styles.reviewCheckboxLabel}>
            <input
              type="checkbox"
              checked={requestReview}
              onChange={(event) => setRequestReview(event.target.checked)}
              disabled={isSubmitting}
            />
            Request human review
          </label>
          <p className={styles.reviewCheckboxHint}>
            CareFlow always flags a result for review when evidence validation finds an issue. Check
            this to request review even when validation passes.
          </p>
        </fieldset>

        <div className={styles.examples}>
          <span className={styles.examplesLabel}>Example workflows:</span>
          <button type="button" className={styles.exampleChip} onClick={() => loadExample("fhir")} disabled={isSubmitting}>
            Policy + Synthetic FHIR
          </button>
          <button
            type="button"
            className={styles.exampleChip}
            onClick={() => loadExample("synpuf")}
            disabled={isSubmitting}
          >
            Policy + Synthetic Claims
          </button>
        </div>

        <div className={styles.submitRow}>
          <button type="submit" className={styles.submitButton} disabled={isSubmitting || !submissionAllowed}>
            {isSubmitting ? "Running evidence workflow…" : "Run Evidence Workflow"}
          </button>
          {!submissionAllowed && blockedReason && <span className={styles.blockedReason}>{blockedReason}</span>}
        </div>
      </form>

      <div aria-live="polite">
        {state.status === "submitting" && <p className={styles.loading}>Running evidence workflow…</p>}
        {state.status === "result" && <WorkflowResult response={state.response} />}
        {state.status === "error" && (
          <ErrorResult category={state.category} requestId={state.requestId} onRetry={handleRetry} />
        )}
      </div>
    </div>
  );
}

function WorkflowResult({ response }: { response: ReviewableQueryResponse }) {
  return (
    <div>
      {response.review_required ? (
        <div className={styles.reviewCreatedPanel}>
          <p className={styles.reviewCreatedHeading}>Review required</p>
          <p>
            Review ID: <span className={styles.technicalDetailInline}>{response.review_id}</span>
          </p>
          {response.review_status && <p>State: {reviewStatusLabel(response.review_status)}</p>}
          <p>Trigger reason(s): {response.review_reason_codes.map((code) => triggerReasonLabel(code)).join(" ")}</p>
          {response.review_id && (
            <Link href={`/reviews/${response.review_id}`} className={styles.viewReviewLink}>
              View review
            </Link>
          )}
        </div>
      ) : (
        <p className={styles.noReviewNote}>No human review was required for this request.</p>
      )}
      <MultiAgentResultView response={response} />
    </div>
  );
}

function ErrorResult({
  category,
  requestId,
  onRetry,
}: {
  category: ReviewableQueryErrorCategory;
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
