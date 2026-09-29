"use client";

import { useEffect, useRef, useState } from "react";
import { useSystemStatusContext } from "./SystemStatusProvider";
import { isStructuredSubmissionAllowed, structuredSubmissionBlockedReason } from "@/lib/structuredReadiness";
import { querySynpufTool, type StructuredErrorCategory } from "@/lib/api/structuredQuery";
import type {
  AbstentionReason,
  SynpufBeneficiarySummary,
  SynpufClaim,
  SynpufClaimDetails,
} from "@/lib/api/orchestrationTypes";
import { DatasetBadge } from "./structured/DatasetBadge";
import { SyntheticDataNotice } from "./structured/SyntheticDataNotice";
import { IdentifierForm } from "./structured/IdentifierForm";
import { RecordCard } from "./structured/RecordCard";
import { RecordFields } from "./structured/RecordFields";
import { EmptyState, StructuredAbstention, StructuredError } from "./structured/StructuredResultStates";
import {
  BENEFICIARY_CHRONIC_FIELDS,
  BENEFICIARY_COVERAGE_FIELDS,
  BENEFICIARY_IDENTITY_FIELDS,
  BENEFICIARY_PAYMENT_FIELDS,
  CLAIM_FIELDS,
} from "./structured/fieldSpecs";
import styles from "./Claims.module.css";

// Queried directly from the live database for this slice (see
// docs/phase14_frontend_design.md's "Demo synthetic IDs") -- confirmed
// present in synpuf_beneficiaries, not fabricated.
const EXAMPLE_BENEFICIARY_ID = "00013D2EFD8E45D1";

type ClaimsTool = "get_beneficiary_summary" | "get_claims_for_beneficiary";

const VIEWS: { tool: ClaimsTool; label: string; loadingLabel: string }[] = [
  {
    tool: "get_beneficiary_summary",
    label: "Beneficiary Overview",
    loadingLabel: "Loading synthetic beneficiary data…",
  },
  { tool: "get_claims_for_beneficiary", label: "Claims", loadingLabel: "Loading synthetic claims…" },
];

type ViewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok"; data: unknown }
  | { status: "abstained"; reason: AbstentionReason }
  | { status: "error"; category: StructuredErrorCategory; requestId: string | null };

type ClaimDetailState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok"; data: SynpufClaimDetails }
  | { status: "abstained"; reason: AbstentionReason }
  | { status: "error"; category: StructuredErrorCategory; requestId: string | null };

function validateId(raw: string): string | null {
  if (raw.trim().length === 0) return "Please enter a synthetic beneficiary ID.";
  return null;
}

export function Claims() {
  const { status: systemStatus } = useSystemStatusContext();
  const [beneficiaryIdInput, setBeneficiaryIdInput] = useState("");
  const [submittedId, setSubmittedId] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<ClaimsTool>("get_beneficiary_summary");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [state, setState] = useState<ViewState>({ status: "idle" });
  const [expandedClaimId, setExpandedClaimId] = useState<string | null>(null);
  const [claimDetail, setClaimDetail] = useState<ClaimDetailState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);
  const detailAbortRef = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      detailAbortRef.current?.abort();
    },
    [],
  );

  const submissionAllowed = isStructuredSubmissionAllowed(systemStatus);
  const blockedReason = structuredSubmissionBlockedReason(systemStatus);
  const isLoading = state.status === "loading";

  async function load(beneficiaryId: string, tool: ClaimsTool) {
    if (isLoading) return;
    setState({ status: "loading" });
    setExpandedClaimId(null);
    setClaimDetail({ status: "idle" });
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const outcome = await querySynpufTool(tool, { beneficiary_id: beneficiaryId }, controller.signal);
    if (controller.signal.aborted) return;

    if (outcome.kind === "ok") {
      setState({ status: "ok", data: outcome.data });
    } else if (outcome.kind === "abstained") {
      setState({ status: "abstained", reason: outcome.reason });
    } else {
      setState({ status: "error", category: outcome.category, requestId: outcome.requestId });
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (isLoading) return;
    const problem = validateId(beneficiaryIdInput);
    if (problem) {
      setValidationError(problem);
      return;
    }
    // Trimmed once validation passes -- see PatientData.tsx's identical
    // rationale (the backend's StrictModel does not strip whitespace).
    const trimmedId = beneficiaryIdInput.trim();
    setValidationError(null);
    setSubmittedId(trimmedId);
    setActiveTool("get_beneficiary_summary");
    void load(trimmedId, "get_beneficiary_summary");
  }

  function handleViewChange(tool: ClaimsTool) {
    if (!submittedId || isLoading || tool === activeTool) return;
    setActiveTool(tool);
    void load(submittedId, tool);
  }

  function handleRetry() {
    if (submittedId) void load(submittedId, activeTool);
  }

  async function handleToggleClaimDetail(claimRowId: string) {
    if (expandedClaimId === claimRowId) {
      setExpandedClaimId(null);
      return;
    }
    setExpandedClaimId(claimRowId);
    setClaimDetail({ status: "loading" });
    detailAbortRef.current?.abort();
    const controller = new AbortController();
    detailAbortRef.current = controller;

    const outcome = await querySynpufTool(
      "get_claim_details",
      { claim_row_id: claimRowId },
      controller.signal,
    );
    if (controller.signal.aborted) return;

    if (outcome.kind === "ok") {
      setClaimDetail({ status: "ok", data: outcome.data as SynpufClaimDetails });
    } else if (outcome.kind === "abstained") {
      setClaimDetail({ status: "abstained", reason: outcome.reason });
    } else {
      setClaimDetail({ status: "error", category: outcome.category, requestId: outcome.requestId });
    }
  }

  const activeView = VIEWS.find((v) => v.tool === activeTool)!;

  return (
    <div className={styles.page}>
      <section>
        <div className={styles.headingRow}>
          <h1 className={styles.heading}>Claims</h1>
          <DatasetBadge name="CMS DE-SynPUF" />
        </div>
        <SyntheticDataNotice>
          These records are synthetic, de-identified demonstration claims data and do not
          represent real Medicare beneficiaries.
        </SyntheticDataNotice>
      </section>

      <IdentifierForm
        inputId="beneficiary-id"
        label="Synthetic Beneficiary ID"
        value={beneficiaryIdInput}
        onChange={setBeneficiaryIdInput}
        onSubmit={handleSubmit}
        exampleId={EXAMPLE_BENEFICIARY_ID}
        onUseExample={() => {
          setBeneficiaryIdInput(EXAMPLE_BENEFICIARY_ID);
          setValidationError(null);
        }}
        isLoading={isLoading}
        loadingLabel="Loading…"
        submitLabel="Load Beneficiary"
        submissionAllowed={submissionAllowed}
        blockedReason={blockedReason}
        validationError={validationError}
      />

      {submittedId && (
        <nav className={styles.viewTabs} aria-label="Claims views">
          {VIEWS.map((view) => (
            <button
              key={view.tool}
              type="button"
              className={view.tool === activeTool ? styles.activeTab : styles.tab}
              onClick={() => handleViewChange(view.tool)}
              disabled={isLoading}
              aria-current={view.tool === activeTool ? "true" : undefined}
            >
              {view.label}
            </button>
          ))}
        </nav>
      )}

      {submittedId && (
        <div aria-live="polite">
          {state.status === "loading" && <p className={styles.loading}>{activeView.loadingLabel}</p>}
          {state.status === "abstained" && <StructuredAbstention reason={state.reason} />}
          {state.status === "error" && (
            <StructuredError category={state.category} requestId={state.requestId} onRetry={handleRetry} />
          )}
          {state.status === "ok" && activeTool === "get_beneficiary_summary" && (
            <BeneficiaryOverview summary={state.data as SynpufBeneficiarySummary} />
          )}
          {state.status === "ok" && activeTool === "get_claims_for_beneficiary" && (
            <ClaimsList
              claims={(state.data as SynpufClaim[]) ?? []}
              expandedClaimId={expandedClaimId}
              onToggle={handleToggleClaimDetail}
              detailState={claimDetail}
            />
          )}
        </div>
      )}
    </div>
  );
}

function BeneficiaryOverview({ summary }: { summary: SynpufBeneficiarySummary }) {
  return (
    <RecordCard>
      <RecordFields record={summary} fields={BENEFICIARY_IDENTITY_FIELDS} />
      <p className={styles.subheading}>Coverage</p>
      <RecordFields record={summary} fields={BENEFICIARY_COVERAGE_FIELDS} />
      <p className={styles.subheading}>Chronic Condition Indicators</p>
      <RecordFields record={summary} fields={BENEFICIARY_CHRONIC_FIELDS} />
      <p className={styles.subheading}>Payment Amounts</p>
      <RecordFields record={summary} fields={BENEFICIARY_PAYMENT_FIELDS} />
    </RecordCard>
  );
}

function ClaimsList({
  claims,
  expandedClaimId,
  onToggle,
  detailState,
}: {
  claims: SynpufClaim[];
  expandedClaimId: string | null;
  onToggle: (claimRowId: string) => void;
  detailState: ClaimDetailState;
}) {
  if (claims.length === 0) return <EmptyState />;

  return (
    <div>
      <p className={styles.recordCount}>
        {claims.length} claim{claims.length === 1 ? "" : "s"}
      </p>
      <ul className={styles.recordList}>
        {claims.map((claim) => (
          <RecordCard key={claim.claim_row_id}>
            <RecordFields record={claim} fields={CLAIM_FIELDS} />
            <button
              type="button"
              className={styles.detailToggle}
              onClick={() => onToggle(claim.claim_row_id)}
              aria-expanded={expandedClaimId === claim.claim_row_id}
            >
              {expandedClaimId === claim.claim_row_id ? "Hide details" : "View details"}
            </button>
            {expandedClaimId === claim.claim_row_id && (
              <div className={styles.claimDetail}>
                {detailState.status === "loading" && (
                  <p className={styles.loading}>Loading synthetic claim details…</p>
                )}
                {detailState.status === "abstained" && <StructuredAbstention reason={detailState.reason} />}
                {detailState.status === "error" && (
                  <StructuredError
                    category={detailState.category}
                    requestId={detailState.requestId}
                    onRetry={() => onToggle(claim.claim_row_id)}
                  />
                )}
                {detailState.status === "ok" && <ClaimDetailView details={detailState.data} />}
              </div>
            )}
          </RecordCard>
        ))}
      </ul>
    </div>
  );
}

function ClaimDetailView({ details }: { details: SynpufClaimDetails }) {
  return (
    <div>
      <p className={styles.subheading}>Diagnoses (ICD-9)</p>
      {details.diagnoses.length === 0 ? (
        <p className={styles.emptyInline}>No diagnosis codes recorded.</p>
      ) : (
        <p className={styles.codeList}>
          {details.diagnoses.map((d) => d.icd9_code).join(", ")}
        </p>
      )}
      <p className={styles.subheading}>Procedures (ICD-9)</p>
      {details.procedures.length === 0 ? (
        <p className={styles.emptyInline}>No procedure codes recorded.</p>
      ) : (
        <p className={styles.codeList}>
          {details.procedures.map((p) => p.icd9_procedure_code).join(", ")}
        </p>
      )}
      <p className={styles.subheading}>Line Items (HCPCS)</p>
      {details.lines.length === 0 ? (
        <p className={styles.emptyInline}>No line-item codes recorded.</p>
      ) : (
        <p className={styles.codeList}>{details.lines.map((l) => l.hcpcs_code).join(", ")}</p>
      )}
    </div>
  );
}
