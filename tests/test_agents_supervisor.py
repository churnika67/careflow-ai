import pytest
from app.agents.models import WorkflowDecision
from app.agents.supervisor import classify_workflow
from app.orchestration.models import AbstentionReason, Route

REAL_FHIR_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"
REAL_SYNPUF_BENEFICIARY_ID = "00013D2EFD8E45D1"


def test_policy_only_request_routes_to_policy_only():
    result = classify_workflow("Does Medicare cover hospital beds?")
    assert result.workflow == WorkflowDecision.POLICY_ONLY
    assert result.structured_route is None


def test_fhir_structured_request_routes_to_structured_only_fhir():
    result = classify_workflow(f"What conditions does patient {REAL_FHIR_PATIENT_ID} have?")
    assert result.workflow == WorkflowDecision.STRUCTURED_ONLY
    assert result.structured_route == Route.FHIR


def test_synpuf_structured_request_routes_to_structured_only_synpuf():
    result = classify_workflow(f"What claims does beneficiary {REAL_SYNPUF_BENEFICIARY_ID} have?")
    assert result.workflow == WorkflowDecision.STRUCTURED_ONLY
    assert result.structured_route == Route.SYNPUF


@pytest.mark.parametrize(
    "question", ["What is the weather?", "Write Python code.", "Who won the game?"]
)
def test_unsupported_requests_abstain(question):
    result = classify_workflow(question)
    assert result.workflow == WorkflowDecision.ABSTAIN
    assert result.abstention_reason == AbstentionReason.UNSUPPORTED_REQUEST


def test_legitimate_combined_request_with_fhir_identifier():
    result = classify_workflow(
        "What does Medicare policy say about hospital beds, and what "
        f"hospital-bed-related information exists for patient {REAL_FHIR_PATIENT_ID}?"
    )
    assert result.workflow == WorkflowDecision.POLICY_AND_STRUCTURED
    assert result.structured_route == Route.FHIR


def test_legitimate_combined_request_with_synpuf_identifier():
    result = classify_workflow(
        "What does Medicare say about coverage for beneficiary "
        f"{REAL_SYNPUF_BENEFICIARY_ID} claims?"
    )
    assert result.workflow == WorkflowDecision.POLICY_AND_STRUCTURED
    assert result.structured_route == Route.SYNPUF


def test_ambiguous_combined_intent_without_an_identifier_does_not_become_combined():
    # Policy signal + a structured keyword but no identifier: must not
    # silently become a combined workflow it can't fulfill.
    result = classify_workflow("Does Medicare coverage apply to this patient's medication?")
    assert result.workflow == WorkflowDecision.ABSTAIN
    assert result.abstention_reason == AbstentionReason.AMBIGUOUS_ROUTE


def test_cross_dataset_identifiers_abstain_not_combined():
    result = classify_workflow(
        f"Compare beneficiary {REAL_SYNPUF_BENEFICIARY_ID} with patient {REAL_FHIR_PATIENT_ID}"
    )
    assert result.workflow == WorkflowDecision.ABSTAIN
    assert result.abstention_reason == AbstentionReason.CROSS_DATASET_LINKAGE_REQUEST


def test_structured_intent_without_identifier_abstains():
    result = classify_workflow("Show me this patient's conditions")
    assert result.workflow == WorkflowDecision.ABSTAIN
    assert result.abstention_reason == AbstentionReason.MISSING_REQUIRED_IDENTIFIER


def test_classification_is_deterministic():
    a = classify_workflow("Does Medicare cover hospital beds?")
    b = classify_workflow("Does Medicare cover hospital beds?")
    assert a == b


def test_supervisor_never_imports_db_or_tool_execution():
    # Structural guard: the supervisor module must have no access to
    # database connections or tool execution — it only classifies text.
    import app.agents.supervisor as supervisor_module

    source = supervisor_module.__file__
    with open(source) as f:
        content = f.read()
    assert "execute_tool" not in content
    assert "psycopg" not in content
    assert "connect(" not in content
