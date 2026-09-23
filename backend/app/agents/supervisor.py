"""The bounded workflow coordinator: deterministic, no DB/retrieval/tool/SQL/
generation access of its own — it only selects among WorkflowDecision values
(and, for structured workflows, which domain). Reuses Phase 9's identifier
patterns, keyword sets, and single-route classifier directly rather than
duplicating them; the only new rule is detecting a combined request."""

import re
from dataclasses import dataclass

from app.agents.models import WorkflowDecision
from app.orchestration.classify import (
    FHIR_ID_PATTERN,
    POLICY_KEYWORDS,
    SYNPUF_ID_PATTERN,
)
from app.orchestration.classify import classify as classify_route
from app.orchestration.models import AbstentionReason, Route


@dataclass(frozen=True)
class WorkflowClassification:
    workflow: WorkflowDecision
    structured_route: Route | None = None
    extracted_id: str | None = None
    abstention_reason: AbstentionReason | None = None


def _keyword_hit(question: str, keywords: frozenset[str]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", question, re.IGNORECASE) for word in keywords)


def classify_workflow(question: str) -> WorkflowClassification:
    """Combined workflow requires a positive policy signal AND a positive,
    UNAMBIGUOUS structured signal — a real extracted identifier for exactly
    one structured domain, not a bare keyword. A structured domain named
    only by keyword (no identifier) alongside a policy signal deliberately
    falls through to Phase 9's classify(), which already reports the
    correct reason (missing_required_identifier for one keyword-only
    domain, or ambiguous_route once policy is counted as a second signal) —
    that decision is not duplicated here. Both structured identifier shapes
    present at once also falls through, where classify() already reports
    cross_dataset_linkage_request."""
    fhir_id = FHIR_ID_PATTERN.search(question)
    synpuf_id = SYNPUF_ID_PATTERN.search(question)
    policy_hit = _keyword_hit(question, POLICY_KEYWORDS)

    if policy_hit and fhir_id and not synpuf_id:
        return WorkflowClassification(
            WorkflowDecision.POLICY_AND_STRUCTURED,
            structured_route=Route.FHIR,
            extracted_id=fhir_id.group(0),
        )
    if policy_hit and synpuf_id and not fhir_id:
        return WorkflowClassification(
            WorkflowDecision.POLICY_AND_STRUCTURED,
            structured_route=Route.SYNPUF,
            extracted_id=synpuf_id.group(0),
        )

    result = classify_route(question)
    if result.route == Route.POLICY:
        return WorkflowClassification(WorkflowDecision.POLICY_ONLY)
    if result.route in (Route.FHIR, Route.SYNPUF):
        return WorkflowClassification(
            WorkflowDecision.STRUCTURED_ONLY,
            structured_route=result.route,
            extracted_id=result.extracted_id,
        )
    return WorkflowClassification(
        WorkflowDecision.ABSTAIN, abstention_reason=result.abstention_reason
    )
