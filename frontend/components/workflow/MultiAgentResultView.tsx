import type {
  MultiAgentPolicyResult,
  MultiAgentResponse,
  MultiAgentStructured,
  ValidationResult,
} from "@/lib/api/multiAgentTypes";
import { workflowLabel, validationIssueMessage } from "@/lib/workflowLabels";
import { PolicyAbstainedResult, PolicyAnswerResult } from "../policy/PolicyAnswer";
import { DatasetBadge } from "../structured/DatasetBadge";
import { SyntheticDataNotice } from "../structured/SyntheticDataNotice";
import { StructuredAbstention } from "../structured/StructuredResultStates";
import { ToolResultView, type WorkflowStructuredTool } from "../structured/ToolResultView";
import styles from "./MultiAgentResultView.module.css";

/**
 * Renders any real MultiAgentResponse-shaped object -- a live POST
 * /multi-agent or /reviewable-query result, OR a Phase 11 review case's
 * stored `evidence_snapshot` (which is exactly
 * `MultiAgentResponse.model_dump(mode="json")`, confirmed from
 * backend/app/review/models.py::build_evidence_snapshot). Extracted from
 * Workflow.tsx in Slice 6 specifically so a review's evidence snapshot is
 * rendered through the EXACT same trusted component as a live result --
 * never a second, independent evidence renderer (see
 * docs/phase14_frontend_design.md's Slice 6 "Evidence rendering" section).
 * This component is read-only: it never fetches, re-runs, or mutates
 * anything -- it only formats the object it is given.
 */
export function MultiAgentResultView({ response }: { response: MultiAgentResponse }) {
  const showPolicy = response.workflow === "policy_only" || response.workflow === "policy_and_structured";
  const showStructured =
    response.workflow === "structured_only" || response.workflow === "policy_and_structured";

  return (
    <div className={styles.result}>
      <div className={styles.routingSummary}>
        <p className={styles.routingSummaryLabel}>Evidence Workflow Result</p>
        <p>Workflow: {workflowLabel(response.workflow)}</p>
      </div>

      {response.workflow === "abstain" && (
        <StructuredAbstention reason={response.abstention_reason ?? "unsupported_request"} />
      )}

      {showPolicy && (
        <section>
          <h2 className={styles.sectionHeading}>Medicare Policy Evidence</h2>
          <PolicySection policy={response.policy} />
        </section>
      )}

      {showStructured && (
        <section>
          <h2 className={styles.sectionHeading}>Synthetic Healthcare Data</h2>
          <StructuredSection structured={response.structured} />
        </section>
      )}

      <section>
        <h2 className={styles.sectionHeading}>Validation</h2>
        <ValidationPanel validation={response.validation} />
      </section>

      {response.workflow === "policy_and_structured" && <SafetyDisclaimer />}
    </div>
  );
}

function PolicySection({ policy }: { policy: MultiAgentPolicyResult | null }) {
  if (policy === null) {
    return <p className={styles.missingSection}>Policy evidence was not returned for this request.</p>;
  }
  if (policy.status === "abstained") {
    return <PolicyAbstainedResult />;
  }
  return <PolicyAnswerResult answer={policy.answer} citations={policy.citations} />;
}

function StructuredSection({ structured }: { structured: MultiAgentStructured | null }) {
  if (structured === null) {
    return <p className={styles.missingSection}>Structured data was not returned for this request.</p>;
  }
  return (
    <div className={styles.structuredSection}>
      <DatasetBadge name={structured.route === "synpuf" ? "CMS DE-SynPUF" : "Synthea FHIR"} />
      <SyntheticDataNotice>
        {structured.route === "synpuf"
          ? "These records are synthetic, de-identified demonstration claims data and do not represent real Medicare beneficiaries."
          : "These records are generated synthetic healthcare data and do not represent real patients."}
      </SyntheticDataNotice>
      {structured.results.map((item, index) => (
        <div key={index}>
          {item.success && item.data !== null ? (
            <>
              {item.record_count !== null && (
                <p className={styles.recordCount}>
                  {item.record_count} record{item.record_count === 1 ? "" : "s"}
                </p>
              )}
              <ToolResultView tool={(item.tool ?? "get_patient_summary") as WorkflowStructuredTool} data={item.data} />
            </>
          ) : item.abstention_reason ? (
            <StructuredAbstention reason={item.abstention_reason} />
          ) : (
            <p className={styles.missingSection}>Structured data could not be retrieved for this request.</p>
          )}
        </div>
      ))}
    </div>
  );
}

function ValidationPanel({ validation }: { validation: ValidationResult | null }) {
  if (validation === null) {
    return <p className={styles.missingSection}>No validation result was returned for this request.</p>;
  }
  if (validation.issues.length === 0) {
    return (
      <p className={styles.validationOk} role="status">
        Evidence validation passed with no issues.
      </p>
    );
  }
  return (
    <div
      className={validation.passed ? styles.validationNotice : styles.validationWarning}
      role={validation.passed ? "status" : "alert"}
    >
      <p>{validation.passed ? "Evidence validation passed with notices:" : "Evidence validation did not pass:"}</p>
      <ul>
        {validation.issues.map((issue, index) => (
          <li key={index}>
            {validationIssueMessage(issue.code)}{" "}
            <span className={styles.technicalDetail}>({issue.code})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SafetyDisclaimer() {
  return (
    <div className={styles.disclaimer} role="note">
      <p className={styles.disclaimerLabel}>Important</p>
      <p>
        Policy information and synthetic healthcare data are shown as separate evidence sources.
        Their presence together does not establish individual coverage, eligibility, medical
        necessity, or claim approval.
      </p>
    </div>
  );
}
