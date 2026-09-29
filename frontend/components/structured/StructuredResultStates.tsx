import type { AbstentionReason } from "@/lib/api/orchestrationTypes";
import type { StructuredErrorCategory } from "@/lib/api/structuredQuery";
import styles from "./StructuredResultStates.module.css";

/** A successful query returning zero records is not an error -- see
 * docs/phase14_frontend_design.md's "Empty-result UX". Never phrased as a
 * clinical/coverage conclusion (e.g. never "patient does not have this
 * condition"), since a bounded lookup tool has no basis for that claim. */
export function EmptyState() {
  return (
    <p className={styles.empty} role="status">
      No records found for this synthetic identifier/query.
    </p>
  );
}

const ABSTENTION_MESSAGES: Record<AbstentionReason, string> = {
  unknown_patient: "No synthetic patient was found for this ID.",
  unknown_beneficiary: "No synthetic beneficiary was found for this ID.",
  unknown_claim: "No synthetic claim was found for this ID.",
  missing_required_identifier: "A synthetic identifier is required for this request.",
  invalid_tool_arguments: "The provided identifier could not be validated.",
  unsupported_tool: "This structured data view is not currently supported.",
  unsupported_request: "CareFlow could not process this structured data request.",
  ambiguous_route: "CareFlow could not determine which dataset to use for this request.",
  cross_dataset_linkage_request: "CareFlow does not link records across datasets.",
  inconsistent_request: "This request combined incompatible options.",
  policy_abstained: "CareFlow could not find enough evidence to answer this question.",
};

export function StructuredAbstention({ reason }: { reason: AbstentionReason }) {
  return (
    <div className={styles.abstained} role="status">
      <p>{ABSTENTION_MESSAGES[reason]}</p>
    </div>
  );
}

const ERROR_MESSAGES: Record<StructuredErrorCategory, string> = {
  network: "CareFlow could not reach the backend. Check your connection and try again.",
  timeout: "The request took too long to complete. Please try again.",
  backend_unavailable: "Structured data is temporarily unavailable. Please try again shortly.",
  unexpected: "Something went wrong while processing this request. Please try again.",
};

export function StructuredError({
  category,
  requestId,
  onRetry,
}: {
  category: StructuredErrorCategory;
  requestId: string | null;
  onRetry: () => void;
}) {
  return (
    <div className={styles.error} role="alert">
      <p>{ERROR_MESSAGES[category]}</p>
      <button type="button" className={styles.retryButton} onClick={onRetry}>
        Retry
      </button>
      {requestId && <p className={styles.technicalDetail}>Request ID: {requestId}</p>}
    </div>
  );
}
