"""Phase 12 Slice 7: lightweight, deterministic governance helpers over the
claim matrix and gap registry -- no new framework, no NLP classifier.

This module validates structure only (required fields present, gap IDs
unique, statuses drawn from the approved enum, required gap categories
covered) and runs a structured, context-aware scan for a short list of
especially dangerous unsupported phrases across Phase 12 evaluation docs.
The scanner is deliberately not a blind grep: a prohibited phrase is only
flagged when it appears OUTSIDE a markdown table's "Disallowed wording"
column and outside a section whose nearest heading names it as a
disallowed/avoid list -- both of those contexts exist precisely to display
prohibited phrases as examples, and displaying an example is not making the
claim."""

import json
import re
from pathlib import Path

APPROVED_GAP_STATUSES = {"OPEN", "DOCUMENTED_LIMITATION", "OUT_OF_SCOPE_PHASE12"}
APPROVED_CLAIM_STATUSES = {"SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_EVALUATED", "OUT_OF_SCOPE"}

REQUIRED_GAP_FIELDS = {
    "gap_id",
    "title",
    "category",
    "status",
    "evidence",
    "impact_on_claims",
    "future_evaluation_needed",
    "production_change_required_now",
}

REQUIRED_GAP_IDS = {
    "EVAL-RUNTIME-CONFIG-DRIFT",
    "EVAL-ANSWER-CORRECTNESS-NOT-EVALUATED",
    "EVAL-CITATION-ENTAILMENT-NOT-EVALUATED",
    "EVAL-ROUTING-ACCURACY-NOT-EVALUATED",
    "EVAL-MULTI-AGENT-ANSWER-QUALITY-NOT-EVALUATED",
    "EVAL-HITL-EFFECTIVENESS-NOT-EVALUATED",
    "EVAL-PRODUCTION-LOAD-LATENCY-NOT-EVALUATED",
    "EVAL-SMALL-HELDOUT-SAMPLE",
    "EVAL-SMALL-POLICY-CORPUS",
    "EVAL-SYNTHETIC-STRUCTURED-DATA-SCALE",
    "EVAL-UNSUPPORTED-HIGH-SIMILARITY",
    "EVAL-RERANKER-FALSE-ABSTENTION",
    "EVAL-SLICE2-CANDIDATE-DEPTH-CONFOUND",
}

# Especially dangerous unsupported phrases -- a short, deliberately bounded
# list, not an attempt at general claim detection.
PROHIBITED_PHRASES = [
    "clinically validated",
    "clinical benchmark",
    "hipaa compliant",
    "hipaa certified",
    "production sla",
    "statistically significant",
    "independent benchmark",
    "external benchmark",
    "production ready",
    "penetration tested",
    "autonomous agents",
]


def load_gap_registry(path: Path) -> dict:
    return json.loads(path.read_text())


def validate_gap_registry(registry: dict) -> list[str]:
    """Returns a list of violation messages; empty means valid. Never
    raises on a malformed registry -- callers decide what to do with
    violations (tests assert the list is empty)."""
    violations: list[str] = []
    gaps = registry.get("gaps")
    if not isinstance(gaps, list) or not gaps:
        return ["registry has no 'gaps' list"]

    ids: list[str] = []
    for i, gap in enumerate(gaps):
        missing = REQUIRED_GAP_FIELDS - set(gap)
        if missing:
            violations.append(f"gap[{i}] missing required fields: {sorted(missing)}")
            continue
        if gap["status"] not in APPROVED_GAP_STATUSES:
            violations.append(f"gap[{i}] ({gap['gap_id']}) has unapproved status {gap['status']!r}")
        if not isinstance(gap["production_change_required_now"], bool):
            violations.append(
                f"gap[{i}] ({gap['gap_id']}) production_change_required_now must be bool"
            )
        ids.append(gap["gap_id"])

    duplicates = {gap_id for gap_id in ids if ids.count(gap_id) > 1}
    if duplicates:
        violations.append(f"duplicate gap_id values: {sorted(duplicates)}")

    missing_required = REQUIRED_GAP_IDS - set(ids)
    if missing_required:
        violations.append(f"missing required gap_id values: {sorted(missing_required)}")

    return violations


def parse_markdown_table(text: str, *, heading_hint: str | None = None) -> list[dict[str, str]]:
    """A minimal '|'-delimited markdown table parser -- not a general
    markdown parser. Finds the first table (optionally the first table
    under a heading containing heading_hint, case-insensitive) and returns
    one dict per data row keyed by the header row's column names."""
    lines = text.splitlines()
    start = 0
    if heading_hint is not None:
        for i, line in enumerate(lines):
            if line.strip().startswith("#") and heading_hint.lower() in line.lower():
                start = i
                break
    table_lines = []
    in_table = False
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("|"):
            in_table = True
            table_lines.append(stripped)
        elif in_table:
            break
    if len(table_lines) < 2:
        return []
    header = [c.strip() for c in table_lines[0].strip("|").split("|")]
    rows = []
    for row_line in table_lines[2:]:  # skip header and the |---|---| separator
        cells = [c.strip() for c in row_line.strip("|").split("|")]
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells, strict=True)))
    return rows


def validate_claim_matrix(rows: list[dict[str, str]]) -> list[str]:
    violations = []
    if not rows:
        return ["no claim matrix rows parsed"]
    for i, row in enumerate(rows):
        status = row.get("Status", "")
        if status not in APPROVED_CLAIM_STATUSES:
            violations.append(f"row[{i}] ({row.get('Claim')!r}) has unapproved status {status!r}")
    return violations


def _heading_is_exempt(heading: str) -> bool:
    lowered = heading.lower()
    return "avoid" in lowered or "disallow" in lowered


def scan_for_prohibited_wording(
    text: str, *, disallowed_column_name: str = "Disallowed wording"
) -> list[dict]:
    """Structured, context-aware scan: a prohibited phrase is flagged only
    when found OUTSIDE (a) a markdown table cell under a column named
    disallowed_column_name, and (b) a line under the nearest preceding
    heading whose text contains "avoid" or "disallow". Both contexts exist
    specifically to display an example of prohibited phrasing, which is not
    itself a violation."""
    findings: list[dict] = []
    current_heading = ""
    header_cols: list[str] | None = None
    disallowed_col_index: int | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if line.startswith("#"):
            current_heading = line
            header_cols = None
            disallowed_col_index = None
            continue

        if _heading_is_exempt(current_heading):
            continue  # entire section is an explicit avoid/disallow listing

        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if header_cols is None and disallowed_column_name in cells:
                header_cols = cells
                disallowed_col_index = cells.index(disallowed_column_name)
                continue
            if (
                header_cols is not None
                and set(cells) <= {"", "---"}
                or all(set(c) <= {"-", ":"} for c in cells)
            ):
                continue  # the |---|---| separator row
            exempt_index = disallowed_col_index if header_cols is not None else None
            for col_index, cell in enumerate(cells):
                if col_index == exempt_index:
                    continue
                _scan_plain_text(cell, line_number, findings)
            continue

        _scan_plain_text(line, line_number, findings)

    return findings


def _scan_plain_text(text: str, line_number: int, findings: list[dict]) -> None:
    lowered = text.lower()
    for phrase in PROHIBITED_PHRASES:
        if re.search(re.escape(phrase), lowered):
            findings.append({"phrase": phrase, "line": line_number, "text": text})
