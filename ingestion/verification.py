from datetime import UTC, datetime


def verify(provider, index, chunks, cases):
    by_id = {c.chunk_id: c for c in chunks}
    results = []
    for case in cases:
        hits = index.search(case["query"], provider, limit=5)
        for hit in hits:
            expected = by_id[hit["chunk_id"]].payload()
            if any(hit.get(key) != value for key, value in expected.items()):
                raise AssertionError(
                    "Returned evidence/provenance differs from source construction"
                )
            if hit["page"] is not None:
                raise AssertionError("CSV evidence must not have page numbers")
        matching = [
            h
            for h in hits
            if h["NCD_id"] == case["expected_document_id"]
            and h["NCD_vrsn_num"] == case["expected_version"]
            and h["source_field"] == "indctn_lmtn"
            and h["section"] == case["expected_section"]
            and case["expected_evidence_phrase"].lower() in h["text"].lower()
        ]
        results.append(
            case
            | {
                "expected_indications_in_top5": bool(matching),
                "expected_evidence_rank": next(
                    (i for i, hit in enumerate(hits, 1) if hit in matching), None
                ),
                "top_results": [
                    {
                        k: h[k]
                        for k in (
                            "chunk_id",
                            "score",
                            "NCD_id",
                            "NCD_vrsn_num",
                            "title",
                            "source_field",
                            "section",
                            "section_char_start",
                            "section_char_end",
                            "viewer_url",
                        )
                    }
                    for h in hits
                ],
            }
        )
    filters = {
        "NCD_id": "226",
        "NCD_vrsn_num": "3",
        "source_field": "indctn_lmtn",
        "coverage_code": "2",
    }
    filtered = index.search("sleep testing and CPAP documentation", provider, filters=filters)
    filter_pass = bool(filtered) and all(
        all(h[k] == v for k, v in filters.items()) for h in filtered
    )
    absent_pass = index.search("oxygen", provider, filters={"NCD_id": "not-in-subset"}) == []
    if not filter_pass or not absent_pass:
        raise AssertionError("Metadata filtering failed")
    return {
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "collection": index.resolve(),
        "queries": results,
        "cases_passed": sum(r["expected_indications_in_top5"] for r in results),
        "cases_total": len(cases),
        "filters_verified": filters,
        "filter_result_count": len(filtered),
        "absent_document_returns_empty": absent_pass,
        "all_returned_payloads_match_source_chunks": True,
        "embedding": provider.describe(),
    }
