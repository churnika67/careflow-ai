import type {
  FhirCondition,
  FhirEncounter,
  FhirMedicationRequest,
  FhirObservation,
  FhirPatientSummary,
  FhirProcedure,
  SynpufBeneficiarySummary,
  SynpufClaim,
} from "@/lib/api/orchestrationTypes";
import { formatCoding, formatCodingList } from "@/lib/formatting";
import { RecordCard } from "./RecordCard";
import { RecordFields } from "./RecordFields";
import { EmptyState } from "./StructuredResultStates";
import {
  BENEFICIARY_CHRONIC_FIELDS,
  BENEFICIARY_COVERAGE_FIELDS,
  BENEFICIARY_IDENTITY_FIELDS,
  BENEFICIARY_PAYMENT_FIELDS,
  CLAIM_FIELDS,
  ENCOUNTER_FIELDS,
  PATIENT_SUMMARY_FIELDS,
} from "./fieldSpecs";
import styles from "./ToolResultView.module.css";

/**
 * The bounded set of single-identifier-scoped tools Evidence Workflow (Phase
 * 14 Slice 5) offers -- the same per-tool rendering Patient Data/Claims
 * (Slice 3) already use, built from the exact same shared primitives
 * (RecordFields, RecordCard, fieldSpecs, formatCoding/formatCodingList).
 * This is not a second, independent rendering system: it is a second page's
 * own tool-to-fields switch, exactly like Patient Data and Claims already
 * each have their own -- assembled from the same shared building blocks,
 * per docs/phase14_frontend_design.md's Slice 5 "Structured result
 * rendering" section.
 *
 * Deliberately excludes get_claim_details: that tool takes a claim_row_id,
 * not a patient/beneficiary identifier, so it has no place in a single
 * "Synthetic identifier" field -- and the interactive claims list here has
 * no per-claim drill-down (this page renders one bounded structured result,
 * not an exploratory surface like Claims itself).
 */
export type WorkflowStructuredTool =
  | "get_patient_summary"
  | "get_patient_encounters"
  | "get_patient_conditions"
  | "get_patient_procedures"
  | "get_patient_observations"
  | "get_patient_medication_requests"
  | "get_beneficiary_summary"
  | "get_claims_for_beneficiary";

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

export function ToolResultView({ tool, data }: { tool: WorkflowStructuredTool; data: unknown }) {
  if (tool === "get_patient_summary") {
    return (
      <RecordCard>
        <RecordFields record={data as FhirPatientSummary} fields={PATIENT_SUMMARY_FIELDS} />
      </RecordCard>
    );
  }

  if (tool === "get_beneficiary_summary") {
    const summary = data as SynpufBeneficiarySummary;
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
                  _coding: formatCoding(observation.code, observation.code_system, observation.code_display),
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

  if (tool === "get_claims_for_beneficiary") {
    return (
      <div>
        {countHeading}
        <ul className={styles.recordList}>
          {(records as SynpufClaim[]).map((claim) => (
            <RecordCard key={claim.claim_row_id}>
              <RecordFields record={claim} fields={CLAIM_FIELDS} />
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
