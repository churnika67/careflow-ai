"""Deterministic free-text routing fallback, used only when a caller has not
supplied an explicit `requested_route`. This is intentionally conservative:
routing requires *positive* evidence for every route, including POLICY —
there is no "no signal found -> POLICY" default, per design.

Two kinds of signal, in priority order:
  1. An identifier SHAPE actually matching a real source identity format
     (a Synthea FHIR resource UUID, or a DE-SynPUF DESYNPUF_ID's 16-hex-char
     shape). This is the strongest signal: an explicit ID is unambiguous.
  2. A small, curated keyword set per domain. Deliberately not a "giant
     keyword list" — each set is a handful of terms specific enough to that
     domain that they do not collide with ordinary conversation ("weather",
     "python code", "who won the game" all match nothing).

Both ID shapes present at once is treated as an attempted cross-dataset
linkage, not "pick one" — DE-SynPUF beneficiaries and Synthea patients are
unrelated populations (see docs/phase8_structured_health_data.md), and a
request naming both is exactly the case Phase 9 must not silently resolve.
"""

import re
from dataclasses import dataclass

from app.orchestration.models import AbstentionReason, Route

FHIR_ID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# DESYNPUF_ID is 16 hex characters; requiring at least one A-F letter avoids
# treating a plain 16-digit number as a beneficiary ID.
SYNPUF_ID_PATTERN = re.compile(r"\b(?=[0-9A-F]{16}\b)[0-9A-F]*[A-F][0-9A-F]*\b")

FHIR_KEYWORDS = frozenset(
    {"fhir", "synthea", "patient", "encounter", "condition", "observation", "medication"}
)
SYNPUF_KEYWORDS = frozenset({"desynpuf", "synpuf", "beneficiary", "claim", "hcpcs"})
POLICY_KEYWORDS = frozenset({"medicare", "cms", "ncd", "coverage", "covered", "cover", "policy"})


@dataclass(frozen=True)
class ClassificationResult:
    route: Route
    extracted_id: str | None = None
    abstention_reason: AbstentionReason | None = None


def _keyword_hit(question: str, keywords: frozenset[str]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", question, re.IGNORECASE) for word in keywords)


def classify(question: str) -> ClassificationResult:
    fhir_id = FHIR_ID_PATTERN.search(question)
    synpuf_id = SYNPUF_ID_PATTERN.search(question)

    if fhir_id and synpuf_id:
        return ClassificationResult(
            Route.ABSTAIN, abstention_reason=AbstentionReason.CROSS_DATASET_LINKAGE_REQUEST
        )
    if fhir_id:
        return ClassificationResult(Route.FHIR, extracted_id=fhir_id.group(0))
    if synpuf_id:
        return ClassificationResult(Route.SYNPUF, extracted_id=synpuf_id.group(0))

    signals = {
        Route.POLICY: _keyword_hit(question, POLICY_KEYWORDS),
        Route.FHIR: _keyword_hit(question, FHIR_KEYWORDS),
        Route.SYNPUF: _keyword_hit(question, SYNPUF_KEYWORDS),
    }
    matched = [route for route, hit in signals.items() if hit]

    if len(matched) > 1:
        return ClassificationResult(
            Route.ABSTAIN, abstention_reason=AbstentionReason.AMBIGUOUS_ROUTE
        )
    if len(matched) == 0:
        return ClassificationResult(
            Route.ABSTAIN, abstention_reason=AbstentionReason.UNSUPPORTED_REQUEST
        )
    if matched[0] == Route.POLICY:
        return ClassificationResult(Route.POLICY)
    # A structured domain was named but no identifier was found in the text.
    return ClassificationResult(
        Route.ABSTAIN, abstention_reason=AbstentionReason.MISSING_REQUIRED_IDENTIFIER
    )
