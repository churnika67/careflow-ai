"""The deterministic review-trigger policy: no LLM, no new signal invented —
review_required is derived directly from MultiAgentResponse.validation,
exactly the same typed output Phase 10's own evidence validator already
produces.

    review_required = explicit_review_requested OR len(validation.issues) > 0

`validation.issues` is non-empty exactly when Phase 10's validate_node found
something structurally off (missing result, success-with-no-citations,
source/domain mismatch, a genuine partial-specialist-failure, or a
policy/structured shape leak). This already subsumes validation.passed ==
False (every ERROR path in app.agents.validator appends at least one issue)
and correctly avoids over-triggering on a combined workflow where one side
cleanly abstains — validate_node deliberately does not record a clean
abstention as an issue, since that is the system working correctly, not a
problem for a human to look at.

A response with no validation at all (should not occur in practice — every
Phase 10 path through validate_node always sets it) is treated the same as
"no issues": never a silent crash, never a spurious review."""

from app.agents.models import MultiAgentResponse
from app.review.models import EXPLICIT_REVIEW_REQUESTED, ReviewTrigger


def determine_review_requirement(
    response: MultiAgentResponse, *, explicit_review_requested: bool = False
) -> ReviewTrigger:
    reason_codes: list[str] = []
    if explicit_review_requested:
        reason_codes.append(EXPLICIT_REVIEW_REQUESTED)

    validation = response.validation or {}
    for issue in validation.get("issues") or []:
        code = issue.get("code") if isinstance(issue, dict) else issue
        if code:
            reason_codes.append(code)

    return ReviewTrigger(review_required=bool(reason_codes), reason_codes=reason_codes)
