from app.agents.models import WorkflowDecision
from app.agents.validator import validate_node
from app.orchestration.models import AbstentionReason, Route, Status

REAL_CITATION = {"chunk_id": "x", "document_id": "227", "document_version": "1"}


def _policy_ok(citations=None):
    return {
        "status": "ok",
        "abstention_reason": None,
        "answer": "some evidence",
        "citations": citations if citations is not None else [REAL_CITATION],
        "insufficient_evidence": False,
    }


def _policy_abstained(reason="no_eligible_evidence"):
    return {"status": "abstained", "abstention_reason": reason, "answer": None, "citations": []}


def _structured_ok(source="cms_desynpuf", tool="get_beneficiary_summary"):
    return [
        {
            "tool": tool,
            "success": True,
            "source_dataset": source,
            "data": {"beneficiary_id": "x"},
            "record_count": 1,
            "error": None,
            "abstention_reason": None,
        }
    ]


def _structured_unknown(reason="unknown_beneficiary", tool="get_beneficiary_summary"):
    return [
        {
            "tool": tool,
            "success": True,
            "source_dataset": "cms_desynpuf",
            "data": None,
            "record_count": 0,
            "error": None,
            "abstention_reason": reason,
        }
    ]


# --- 2/3/4: presence requirements per workflow ---


def test_policy_only_requires_policy_result():
    update = validate_node({"workflow": WorkflowDecision.POLICY_ONLY})
    assert update["status"] == Status.ERROR
    assert update["validation"]["passed"] is False
    assert update["validation"]["issues"][0]["code"] == "missing_policy_result"


def test_structured_only_requires_structured_result():
    update = validate_node({"workflow": WorkflowDecision.STRUCTURED_ONLY})
    assert update["status"] == Status.ERROR
    assert update["validation"]["issues"][0]["code"] == "missing_structured_result"


def test_combined_requires_both_results():
    update = validate_node(
        {
            "workflow": WorkflowDecision.POLICY_AND_STRUCTURED,
            "policy_result": _policy_ok(),
            # structured_results missing
        }
    )
    assert update["status"] == Status.ERROR
    assert update["validation"]["issues"][0]["code"] == "missing_structured_result"


# --- 5: policy success requires citations ---


def test_policy_success_without_citations_fails_validation():
    update = validate_node(
        {"workflow": WorkflowDecision.POLICY_ONLY, "policy_result": _policy_ok(citations=[])}
    )
    assert update["status"] == Status.ERROR
    assert update["validation"]["issues"][0]["code"] == "missing_policy_citations"


def test_policy_success_with_citations_passes():
    update = validate_node(
        {"workflow": WorkflowDecision.POLICY_ONLY, "policy_result": _policy_ok()}
    )
    assert update["status"] == Status.OK
    assert update["validation"] == {"passed": True, "issues": []}


def test_policy_abstention_is_preserved_not_a_validation_failure():
    update = validate_node(
        {"workflow": WorkflowDecision.POLICY_ONLY, "policy_result": _policy_abstained()}
    )
    assert update["status"] == Status.ABSTAINED
    assert update["abstention_reason"] == AbstentionReason.POLICY_ABSTAINED
    assert update["validation"]["passed"] is True


# --- 6/7/8: structured results identify source_dataset correctly ---


def test_fhir_structured_result_source_is_synthea_fhir():
    update = validate_node(
        {
            "workflow": WorkflowDecision.STRUCTURED_ONLY,
            "structured_route": Route.FHIR,
            "structured_results": _structured_ok(source="synthea_fhir", tool="get_patient_summary"),
        }
    )
    assert update["status"] == Status.OK
    assert update["validation"]["issues"] == []


def test_synpuf_structured_result_source_is_cms_desynpuf():
    update = validate_node(
        {
            "workflow": WorkflowDecision.STRUCTURED_ONLY,
            "structured_route": Route.SYNPUF,
            "structured_results": _structured_ok(source="cms_desynpuf"),
        }
    )
    assert update["status"] == Status.OK
    assert update["validation"]["issues"] == []


def test_source_mismatch_is_flagged_as_an_issue():
    # Defense in depth: a structured result whose source_dataset does not
    # match its route's expected domain (should be structurally unreachable
    # via execute_tool's own domain check, but the validator re-verifies).
    update = validate_node(
        {
            "workflow": WorkflowDecision.STRUCTURED_ONLY,
            "structured_route": Route.FHIR,
            "structured_results": _structured_ok(source="cms_desynpuf"),
        }
    )
    assert update["validation"]["issues"][0]["code"] == "source_mismatch"


# --- 10: failed/abstained specialist output is surfaced ---


def test_unknown_record_abstention_is_surfaced_in_state():
    update = validate_node(
        {
            "workflow": WorkflowDecision.STRUCTURED_ONLY,
            "structured_route": Route.SYNPUF,
            "structured_results": _structured_unknown(),
        }
    )
    assert update["status"] == Status.ABSTAINED
    assert update["abstention_reason"] == AbstentionReason.UNKNOWN_BENEFICIARY


def test_partial_multi_tool_failure_is_surfaced_as_specialist_failure_issue():
    mixed = _structured_ok() + _structured_unknown()
    update = validate_node(
        {
            "workflow": WorkflowDecision.STRUCTURED_ONLY,
            "structured_route": Route.SYNPUF,
            "structured_results": mixed,
        }
    )
    assert update["status"] == Status.OK  # partial success is still a legitimate response
    codes = [issue["code"] for issue in update["validation"]["issues"]]
    assert "specialist_failure" in codes


# --- 11/12: policy/structured shapes must never bleed into each other ---


def test_structured_shaped_fields_inside_policy_result_are_flagged():
    bad_policy_result = _policy_ok() | {"tool": "get_beneficiary_summary", "source_dataset": "x"}
    update = validate_node(
        {"workflow": WorkflowDecision.POLICY_ONLY, "policy_result": bad_policy_result}
    )
    codes = [issue["code"] for issue in update["validation"]["issues"]]
    assert "workflow_result_mismatch" in codes


def test_policy_shaped_fields_inside_structured_result_are_flagged():
    bad_structured = [_structured_ok()[0] | {"citations": [REAL_CITATION]}]
    update = validate_node(
        {
            "workflow": WorkflowDecision.STRUCTURED_ONLY,
            "structured_route": Route.SYNPUF,
            "structured_results": bad_structured,
        }
    )
    codes = [issue["code"] for issue in update["validation"]["issues"]]
    assert "workflow_result_mismatch" in codes


# --- combined workflow status combination ---


def test_combined_both_ok_is_overall_ok():
    update = validate_node(
        {
            "workflow": WorkflowDecision.POLICY_AND_STRUCTURED,
            "policy_result": _policy_ok(),
            "structured_route": Route.FHIR,
            "structured_results": _structured_ok(source="synthea_fhir", tool="get_patient_summary"),
        }
    )
    assert update["status"] == Status.OK
    assert update["validation"]["passed"] is True


def test_combined_one_side_abstains_other_succeeds_is_overall_ok():
    update = validate_node(
        {
            "workflow": WorkflowDecision.POLICY_AND_STRUCTURED,
            "policy_result": _policy_ok(),
            "structured_route": Route.FHIR,
            "structured_results": _structured_unknown(tool="get_patient_summary"),
        }
    )
    assert update["status"] == Status.OK  # real policy evidence exists
    # the structured abstention is still visible in structured_results itself,
    # not duplicated into validation.issues (a single clean abstention is not
    # a "problem" — see the module docstring).


def test_combined_both_sides_abstain_is_overall_abstained():
    update = validate_node(
        {
            "workflow": WorkflowDecision.POLICY_AND_STRUCTURED,
            "policy_result": _policy_abstained(),
            "structured_route": Route.FHIR,
            "structured_results": _structured_unknown(tool="get_patient_summary"),
        }
    )
    assert update["status"] == Status.ABSTAINED
    assert update["abstention_reason"] == AbstentionReason.POLICY_ABSTAINED


def test_combined_error_on_either_side_is_overall_error():
    update = validate_node(
        {
            "workflow": WorkflowDecision.POLICY_AND_STRUCTURED,
            "policy_result": None,  # missing -> error
            "structured_route": Route.FHIR,
            "structured_results": _structured_ok(source="synthea_fhir"),
        }
    )
    assert update["status"] == Status.ERROR
    assert update["validation"]["passed"] is False


# --- abstain workflow ---


def test_abstain_workflow_is_trivially_valid():
    update = validate_node({"workflow": WorkflowDecision.ABSTAIN})
    assert update["status"] == Status.ABSTAINED
    assert update["validation"] == {"passed": True, "issues": []}


def test_validator_is_deterministic():
    state = {"workflow": WorkflowDecision.POLICY_ONLY, "policy_result": _policy_ok()}
    assert validate_node(state) == validate_node(state)


def test_validator_touches_no_retrieval_or_database():
    import app.agents.validator as module

    with open(module.__file__) as f:
        content = f.read()
    for forbidden in ("execute_tool", "psycopg", "connect(", "get_rag_service", "Qdrant"):
        assert forbidden not in content
