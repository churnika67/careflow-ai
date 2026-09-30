"use client";

import { useEffect, useRef, useState } from "react";
import { useSystemStatusContext } from "./SystemStatusProvider";
import { isStructuredSubmissionAllowed, structuredSubmissionBlockedReason } from "@/lib/structuredReadiness";
import { queryFhirTool, type StructuredErrorCategory } from "@/lib/api/structuredQuery";
import type {
  AbstentionReason,
  FhirCondition,
  FhirEncounter,
  FhirMedicationRequest,
  FhirObservation,
  FhirPatientSummary,
  FhirProcedure,
  FhirToolName,
} from "@/lib/api/orchestrationTypes";
import { formatCoding, formatCodingList } from "@/lib/formatting";
import { DatasetBadge } from "./structured/DatasetBadge";
import { SyntheticDataNotice } from "./structured/SyntheticDataNotice";
import { IdentifierForm } from "./structured/IdentifierForm";
import { RecordCard } from "./structured/RecordCard";
import { RecordFields } from "./structured/RecordFields";
import { EmptyState, StructuredAbstention, StructuredError } from "./structured/StructuredResultStates";
import { ENCOUNTER_FIELDS, PATIENT_SUMMARY_FIELDS } from "./structured/fieldSpecs";
import styles from "./PatientData.module.css";

// Queried directly from the live database for this slice (see
// docs/phase14_frontend_design.md's "Demo synthetic IDs") -- confirmed
// present in fhir_patients, not fabricated.
const EXAMPLE_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713";

interface ViewSpec {
  tool: FhirToolName;
  label: string;
  loadingLabel: string;
}

// Only the 6 patient-ID-scoped tools -- the 4 population-level aggregate
// FHIR tools (fhir_encounter_counts, fhir_condition_frequency,
// fhir_procedure_frequency, fhir_medication_frequency) are deliberately
// out of scope for this per-patient page; see the design doc.
const VIEWS: ViewSpec[] = [
  { tool: "get_patient_summary", label: "Summary", loadingLabel: "Loading synthetic patient data…" },
  { tool: "get_patient_encounters", label: "Encounters", loadingLabel: "Loading synthetic encounters…" },
  { tool: "get_patient_conditions", label: "Conditions", loadingLabel: "Loading synthetic conditions…" },
  { tool: "get_patient_procedures", label: "Procedures", loadingLabel: "Loading synthetic procedures…" },
  { tool: "get_patient_observations", label: "Observations", loadingLabel: "Loading synthetic observations…" },
  {
    tool: "get_patient_medication_requests",
    label: "Medications",
    loadingLabel: "Loading synthetic medications…",
  },
];

type ViewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok"; data: unknown; recordCount: number | null }
  | { status: "abstained"; reason: AbstentionReason }
  | { status: "error"; category: StructuredErrorCategory; requestId: string | null };

function validateId(raw: string): string | null {
  if (raw.trim().length === 0) return "Please enter a synthetic patient ID.";
  return null;
}

export function PatientData() {
  const { status: systemStatus } = useSystemStatusContext();
  const [patientIdInput, setPatientIdInput] = useState("");
  const [submittedPatientId, setSubmittedPatientId] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<FhirToolName>("get_patient_summary");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [state, setState] = useState<ViewState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const submissionAllowed = isStructuredSubmissionAllowed(systemStatus);
  const blockedReason = structuredSubmissionBlockedReason(systemStatus);
  const isLoading = state.status === "loading";

  async function load(patientId: string, tool: FhirToolName) {
    if (isLoading) return;
    setState({ status: "loading" });
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const outcome = await queryFhirTool(tool, { patient_id: patientId }, controller.signal);
    if (controller.signal.aborted) return;

    if (outcome.kind === "ok") {
      setState({ status: "ok", data: outcome.data, recordCount: outcome.recordCount });
    } else if (outcome.kind === "abstained") {
      setState({ status: "abstained", reason: outcome.reason });
    } else {
      setState({ status: "error", category: outcome.category, requestId: outcome.requestId });
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (isLoading) return;
    const problem = validateId(patientIdInput);
    if (problem) {
      setValidationError(problem);
      return;
    }
    // Trimmed once validation passes -- the backend's StrictModel does not
    // strip whitespace itself, so a stray leading/trailing space (e.g.
    // from a paste) must not silently turn a valid ID into an "unknown
    // patient" abstention.
    const trimmedId = patientIdInput.trim();
    setValidationError(null);
    setSubmittedPatientId(trimmedId);
    setActiveTool("get_patient_summary");
    void load(trimmedId, "get_patient_summary");
  }

  function handleViewChange(tool: FhirToolName) {
    if (!submittedPatientId || isLoading || tool === activeTool) return;
    setActiveTool(tool);
    void load(submittedPatientId, tool);
  }

  function handleRetry() {
    if (submittedPatientId) void load(submittedPatientId, activeTool);
  }

  const activeView = VIEWS.find((v) => v.tool === activeTool)!;

  return (
    <div className={styles.page}>
      <section>
        <div className={styles.headingRow}>
          <span className={styles.headingIcon} aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 20a8 8 0 0 1 16 0" />
            </svg>
          </span>
          <h1 className={styles.heading}>Patient Data</h1>
          <DatasetBadge name="Synthea FHIR" />
        </div>
        <SyntheticDataNotice>
          These records are generated synthetic healthcare data and do not represent real
          patients.
        </SyntheticDataNotice>
      </section>

      <IdentifierForm
        inputId="patient-id"
        label="Synthetic Patient ID"
        value={patientIdInput}
        onChange={setPatientIdInput}
        onSubmit={handleSubmit}
        exampleId={EXAMPLE_PATIENT_ID}
        onUseExample={() => {
          setPatientIdInput(EXAMPLE_PATIENT_ID);
          setValidationError(null);
        }}
        isLoading={isLoading}
        loadingLabel="Loading…"
        submitLabel="Load Patient"
        submissionAllowed={submissionAllowed}
        blockedReason={blockedReason}
        validationError={validationError}
      />

      {submittedPatientId && (
        <nav className={styles.viewTabs} aria-label="Patient data views">
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

      {submittedPatientId && (
        <div aria-live="polite">
          {state.status === "loading" && <p className={styles.loading}>{activeView.loadingLabel}</p>}
          {state.status === "abstained" && <StructuredAbstention reason={state.reason} />}
          {state.status === "error" && (
            <StructuredError category={state.category} requestId={state.requestId} onRetry={handleRetry} />
          )}
          {state.status === "ok" && <PatientView tool={activeTool} data={state.data} />}
        </div>
      )}
    </div>
  );
}

function PatientView({ tool, data }: { tool: FhirToolName; data: unknown }) {
  if (tool === "get_patient_summary") {
    const summary = data as FhirPatientSummary;
    return (
      <RecordCard>
        <RecordFields record={summary} fields={PATIENT_SUMMARY_FIELDS} />
      </RecordCard>
    );
  }

  const records = (data as unknown[]) ?? [];
  if (records.length === 0) return <EmptyState />;

  const countHeading = (
    <p className={styles.recordCount}>
      {records.length} record{records.length === 1 ? "" : "s"}
    </p>
  );

  if (tool === "get_patient_encounters") {
    return (
      <div>
        {countHeading}
        <ul className={styles.recordList}>
          {(records as FhirEncounter[]).map((encounter) => (
            <RecordCard key={encounter.encounter_id}>
              <RecordFields record={encounter} fields={ENCOUNTER_FIELDS} />
            </RecordCard>
          ))}
        </ul>
      </div>
    );
  }

  if (tool === "get_patient_conditions") {
    return (
      <div>
        {countHeading}
        <ul className={styles.recordList}>
          {(records as FhirCondition[]).map((condition) => (
            <RecordCard key={condition.condition_id}>
              <RecordFields
                record={{
                  ...condition,
                  _coding: formatCoding(condition.code, condition.code_system, condition.code_display),
                }}
                fields={[
                  { key: "_coding", label: "Condition" },
                  { key: "clinical_status", label: "Clinical Status" },
                  { key: "verification_status", label: "Verification Status" },
                  { key: "onset_datetime", label: "Onset", kind: "timestamp" },
                  { key: "recorded_date", label: "Recorded", kind: "timestamp" },
                ]}
              />
              {condition.codings.length > 1 && (
                <p className={styles.allCodings}>All codes: {formatCodingList(condition.codings)}</p>
              )}
            </RecordCard>
          ))}
        </ul>
      </div>
    );
  }

  if (tool === "get_patient_procedures") {
    return (
      <div>
        {countHeading}
        <ul className={styles.recordList}>
          {(records as FhirProcedure[]).map((procedure) => (
            <RecordCard key={procedure.procedure_id}>
              <RecordFields
                record={{
                  ...procedure,
                  _coding: formatCoding(procedure.code, procedure.code_system, procedure.code_display),
                }}
                fields={[
                  { key: "_coding", label: "Procedure" },
                  { key: "status", label: "Status" },
                  { key: "performed_start", label: "Performed (start)", kind: "timestamp" },
                  { key: "performed_end", label: "Performed (end)", kind: "timestamp" },
                ]}
              />
              {procedure.codings.length > 1 && (
                <p className={styles.allCodings}>All codes: {formatCodingList(procedure.codings)}</p>
              )}
            </RecordCard>
          ))}
        </ul>
      </div>
    );
  }

  if (tool === "get_patient_observations") {
    return (
      <div>
        {countHeading}
        <ul className={styles.recordList}>
          {(records as FhirObservation[]).map((observation) => (
            <RecordCard key={observation.observation_id}>
              <RecordFields
                record={{
                  ...observation,
                  _coding: formatCoding(
                    observation.code,
                    observation.code_system,
                    observation.code_display,
                  ),
                  _value: formatObservationValue(observation),
                }}
                fields={[
                  { key: "_coding", label: "Observation" },
                  { key: "status", label: "Status" },
                  { key: "_value", label: "Value" },
                  { key: "effective_datetime", label: "Effective", kind: "timestamp" },
                ]}
              />
              {observation.value_type === "component" &&
                observation.components &&
                observation.components.length > 0 && (
                  <ul className={styles.componentList}>
                    {observation.components.map((component) => (
                      <li key={component.component_index}>
                        {formatCoding(component.code, component.code_system, component.code_display)}:{" "}
                        {component.value_quantity ?? "—"} {component.value_unit ?? ""}
                      </li>
                    ))}
                  </ul>
                )}
            </RecordCard>
          ))}
        </ul>
      </div>
    );
  }

  // get_patient_medication_requests
  return (
    <div>
      {countHeading}
      <ul className={styles.recordList}>
        {(records as FhirMedicationRequest[]).map((medication) => (
          <RecordCard key={medication.medication_request_id}>
            <RecordFields
              record={{
                ...medication,
                _coding: formatCoding(medication.code, medication.code_system, medication.code_display),
              }}
              fields={[
                { key: "_coding", label: "Medication" },
                { key: "status", label: "Status" },
                { key: "intent", label: "Intent" },
                { key: "authored_on", label: "Authored", kind: "timestamp" },
              ]}
            />
          </RecordCard>
        ))}
      </ul>
    </div>
  );
}

function formatObservationValue(observation: FhirObservation): string {
  switch (observation.value_type) {
    case "quantity":
      return `${observation.value_quantity ?? "—"} ${observation.value_unit ?? ""}`.trim();
    case "codeable_concept":
      return observation.value_code_display ?? observation.value_code ?? "—";
    case "string":
      return observation.value_string ?? "—";
    case "component":
      return "See components below";
    default:
      return "—";
  }
}
