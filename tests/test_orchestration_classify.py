import pytest
from app.orchestration.classify import classify
from app.orchestration.models import AbstentionReason, Route

REAL_FHIR_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"
REAL_SYNPUF_BENEFICIARY_ID = "00013D2EFD8E45D1"


def test_policy_question_routes_to_policy():
    result = classify("Does Medicare cover hospital beds?")
    assert result.route == Route.POLICY
    assert result.abstention_reason is None


def test_fhir_identifier_routes_to_fhir_regardless_of_wording():
    result = classify(f"What conditions does patient {REAL_FHIR_PATIENT_ID} have?")
    assert result.route == Route.FHIR
    assert result.extracted_id == REAL_FHIR_PATIENT_ID


def test_synpuf_identifier_routes_to_synpuf_regardless_of_wording():
    result = classify(f"List the claims for beneficiary {REAL_SYNPUF_BENEFICIARY_ID}")
    assert result.route == Route.SYNPUF
    assert result.extracted_id == REAL_SYNPUF_BENEFICIARY_ID


@pytest.mark.parametrize(
    "question",
    ["What is the weather?", "Write Python code.", "Who won the game?"],
)
def test_unrelated_questions_abstain_rather_than_defaulting_to_policy(question):
    result = classify(question)
    assert result.route == Route.ABSTAIN
    assert result.abstention_reason == AbstentionReason.UNSUPPORTED_REQUEST


def test_fhir_intent_without_an_identifier_abstains_missing_required_identifier():
    result = classify("Show me this patient's conditions")
    assert result.route == Route.ABSTAIN
    assert result.abstention_reason == AbstentionReason.MISSING_REQUIRED_IDENTIFIER


def test_synpuf_intent_without_an_identifier_abstains_missing_required_identifier():
    result = classify("What claims does this beneficiary have")
    assert result.route == Route.ABSTAIN
    assert result.abstention_reason == AbstentionReason.MISSING_REQUIRED_IDENTIFIER


def test_conflicting_route_signals_without_an_identifier_abstain_ambiguous():
    result = classify("Does Medicare coverage apply to this patient's medication?")
    assert result.route == Route.ABSTAIN
    assert result.abstention_reason == AbstentionReason.AMBIGUOUS_ROUTE


def test_both_dataset_identifiers_present_abstains_cross_dataset_linkage():
    result = classify(
        f"Compare beneficiary {REAL_SYNPUF_BENEFICIARY_ID} with patient {REAL_FHIR_PATIENT_ID}"
    )
    assert result.route == Route.ABSTAIN
    assert result.abstention_reason == AbstentionReason.CROSS_DATASET_LINKAGE_REQUEST


def test_fhir_identifier_present_wins_over_unrelated_keyword_noise():
    # An explicit, real identifier is the strongest signal regardless of
    # what else is in the sentence.
    result = classify(f"random unrelated words {REAL_FHIR_PATIENT_ID} more words")
    assert result.route == Route.FHIR


def test_classification_is_deterministic_for_the_same_input():
    a = classify("Does Medicare cover hospital beds?")
    b = classify("Does Medicare cover hospital beds?")
    assert a == b


def test_plain_16_digit_number_is_not_mistaken_for_a_synpuf_id():
    # SYNPUF_ID_PATTERN requires at least one A-F hex letter; an all-digit
    # 16-character number must not be treated as a beneficiary ID.
    result = classify("My order number is 1234567890123456, is that covered?")
    assert result.route != Route.SYNPUF
