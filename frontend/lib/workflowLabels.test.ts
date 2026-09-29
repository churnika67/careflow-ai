import { describe, expect, it } from "vitest";
import { validationIssueMessage, workflowLabel } from "./workflowLabels";
import type { ValidationIssueCode } from "./api/multiAgentTypes";

describe("workflowLabel", () => {
  it("maps every real WorkflowDecision value to a human label", () => {
    expect(workflowLabel("policy_only")).toBe("Medicare Policy Only");
    expect(workflowLabel("structured_only")).toBe("Synthetic Data Only");
    expect(workflowLabel("policy_and_structured")).toBe("Medicare Policy + Synthetic Data");
    expect(workflowLabel("abstain")).toBe("No supported workflow");
  });
});

describe("validationIssueMessage", () => {
  const codes: ValidationIssueCode[] = [
    "missing_policy_result",
    "missing_policy_citations",
    "missing_structured_result",
    "source_mismatch",
    "specialist_failure",
    "cross_dataset_identity_violation",
    "workflow_result_mismatch",
  ];

  it("maps every real ValidationIssueCode to a non-empty, calm human message", () => {
    for (const code of codes) {
      const message = validationIssueMessage(code);
      expect(message.length).toBeGreaterThan(0);
      expect(message).not.toBe(code);
    }
  });

  it("never mentions AI/clinical/coverage confidence", () => {
    for (const code of codes) {
      expect(validationIssueMessage(code)).not.toMatch(/confidence/i);
    }
  });
});
