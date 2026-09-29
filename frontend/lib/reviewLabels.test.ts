import { describe, expect, it } from "vitest";
import {
  reviewDecisionLabel,
  reviewEventLabel,
  reviewStatusLabel,
  triggerReasonLabel,
} from "./reviewLabels";

describe("reviewStatusLabel", () => {
  it("maps every real ReviewStatus value to a human label", () => {
    expect(reviewStatusLabel("pending")).toBe("Pending");
    expect(reviewStatusLabel("approved")).toBe("Approved");
    expect(reviewStatusLabel("rejected")).toBe("Rejected");
    expect(reviewStatusLabel("revision_requested")).toBe("Revision Requested");
  });
});

describe("reviewDecisionLabel", () => {
  it("maps every real ReviewDecisionType to its exact backend action, never an invented one", () => {
    expect(reviewDecisionLabel("approve")).toBe("Approve");
    expect(reviewDecisionLabel("reject")).toBe("Reject");
    expect(reviewDecisionLabel("request_revision")).toBe("Request Revision");
  });

  it("never labels a decision as Override, Auto Approve, Escalate, or Approve Coverage", () => {
    const labels = [reviewDecisionLabel("approve"), reviewDecisionLabel("reject"), reviewDecisionLabel("request_revision")];
    for (const label of labels) {
      expect(label).not.toMatch(/override|auto.approve|escalate|coverage/i);
    }
  });
});

describe("reviewEventLabel", () => {
  it("maps every real ReviewEventType to a human label", () => {
    expect(reviewEventLabel("review_created")).toBe("Review created");
    expect(reviewEventLabel("review_approved")).toBe("Approved");
    expect(reviewEventLabel("review_rejected")).toBe("Rejected");
    expect(reviewEventLabel("revision_requested")).toBe("Revision requested");
  });
});

describe("triggerReasonLabel", () => {
  it("labels explicit_review_requested distinctly from validation issue codes", () => {
    expect(triggerReasonLabel("explicit_review_requested")).toMatch(/explicitly requested/i);
  });

  it("reuses Slice 5's validationIssueMessage for every ValidationIssueCode trigger reason", () => {
    expect(triggerReasonLabel("missing_policy_citations")).toBe(
      "The policy answer was returned without supporting citations.",
    );
    expect(triggerReasonLabel("source_mismatch")).toBe(
      "The structured data did not come from the expected dataset.",
    );
    expect(triggerReasonLabel("specialist_failure")).toBe(
      "Part of this request's evidence gathering did not complete successfully.",
    );
  });
});
