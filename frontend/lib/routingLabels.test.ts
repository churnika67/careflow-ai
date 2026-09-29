import { describe, expect, it } from "vitest";
import { routeLabel, toolLabel } from "./routingLabels";

describe("routeLabel", () => {
  it("maps each route to its documented human label", () => {
    expect(routeLabel("policy")).toBe("Medicare Policy");
    expect(routeLabel("fhir")).toBe("Synthea FHIR · Synthetic");
    expect(routeLabel("synpuf")).toBe("CMS DE-SynPUF · Synthetic");
    expect(routeLabel("abstain")).toBe("No supported route");
  });
});

describe("toolLabel", () => {
  it("maps a known tool name to its human label", () => {
    expect(toolLabel("get_patient_summary")).toBe("Patient Summary");
    expect(toolLabel("get_beneficiary_summary")).toBe("Beneficiary Summary");
    expect(toolLabel("get_patient_conditions")).toBe("Patient Conditions");
    expect(toolLabel("get_claims_for_beneficiary")).toBe("Beneficiary Claims");
  });

  it("falls back to the raw tool name for an unmapped value, never fabricating a label", () => {
    expect(toolLabel("some_future_tool")).toBe("some_future_tool");
  });
});
