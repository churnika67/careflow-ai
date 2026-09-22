from collections import Counter

from evaluation.analysis import MODES


def render_report(report):
    def value(x):
        return "—" if x is None else f"{x:.3f}"

    lines = [
        "# CMS retrieval development evaluation v1",
        "",
        "This is a development evaluation over a small curated CMS NCD corpus and "
        "is not a clinical or production benchmark.",
        "",
        f"Observed: {report['observed_at']}. Dataset: `{report['dataset_version']}`.",
        f"Corpus: {report['corpus']['documents']} NCD versions, "
        f"{report['corpus']['sections']} sections, {report['corpus']['chunks']} chunks.",
        f"Corpus fingerprint: `{report['corpus']['fingerprint']}`.",
        f"Dataset fingerprint: `{report['dataset_sha256']}`.",
        f"Stable observations: `{report['stable_observations_sha256']}`.",
        "",
        "## Dataset and configuration",
        "",
        f"Cases: {len(report['cases'])}; "
        f"positive: {sum(c['answerable'] for c in report['cases'])}; "
        f"negative/ambiguous: {sum(not c['answerable'] for c in report['cases'])}.",
        "Category counts: " + str(dict(Counter(c["category"] for c in report["cases"]))) + ".",
        "",
        "Pinned MiniLM embedding and cross-encoder identities, packages and device "
        "are recorded in the JSON configuration. RRF k=60; candidate pool=10; final "
        "top-k=5; cosine gate=0.6; context=24,000 characters. No ranking tuning.",
        "",
        "## Retrieval metrics",
        "",
        "Only positive cases contribute. MRR@5 uses the first acceptable chunk "
        "rank; misses contribute zero. Multiple acceptable IDs are alternatives, "
        "not a requirement to retrieve all of them.",
        "",
        "| Mode | Cases | Hit@1 | Hit@3 | Hit@5 | MRR@5 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in MODES:
        m = report["metrics"][mode]["overall"]
        lines.append(
            f"| {mode} | {m['count']} | "
            + " | ".join(value(m[k]) for k in ("Hit@1", "Hit@3", "Hit@5", "MRR@5"))
            + " |"
        )
    lines += [
        "",
        "## Category results",
        "",
        "| Category | Mode | Positive cases | Hit@1 | Hit@3 | Hit@5 | MRR@5 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category in report["metrics"]["dense"]["categories"]:
        for mode in MODES:
            m = report["metrics"][mode]["categories"][category]
            lines.append(
                f"| {category} | {mode} | {m['count']} | "
                + " | ".join(value(m[k]) for k in ("Hit@1", "Hit@3", "Hit@5", "MRR@5"))
                + " |"
            )
    lines += [
        "",
        "## Reranking changes",
        "",
        str(report["reranking"]),
        "",
        "Improved/degraded compares the first acceptable rank in top five; a miss "
        "is censored after rank five. Two misses are unchanged. Mean rank delta is "
        "before minus after only where both are observed; positive means "
        "improvement.",
        "",
        "## Negative and abstention behavior",
        "",
        "Abstention is the positive prediction for these metrics. TP = abstention "
        "on an unanswerable case; FP = abstention on an answerable case; FN = an "
        "answer attempt on an unanswerable case. Precision = TP/(TP+FP); recall = "
        "TP/(TP+FN). Undefined ratios are null. This evaluates the deterministic "
        "provider, not clinical answer quality.",
        "",
        "| Mode | Negatives | Correct abstentions | Incorrect attempts | Positive "
        "abstentions | Precision | Recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, m in report["abstention"].items():
        lines.append(
            f"| {mode} | {m['negative_cases']} | {m['correct_abstentions']} | "
            f"{m['incorrect_answer_attempts']} | {m['positive_abstentions']} | "
            f"{value(m['precision'])} | {value(m['recall'])} |"
        )
    lines += [
        "",
        "## Latency",
        "",
        "Sequential warm calls; all cases repeated as configured. Retrieval "
        "includes Qdrant I/O and BM25 rebuilding where applicable, excludes model "
        "loading and generation. Candidate timing additionally includes the "
        "existing dense evidence-gate lookup at depth 20. Rerank-only timing scores "
        "the ten retrieved candidates, excludes their retrieval and generation. p95 "
        "uses nearest-rank ceil(0.95*n). These are not end-to-end or "
        "concurrent-load timings.",
        "",
        "| Stage | Calls | Median ms | p95 ms |",
        "| --- | ---: | ---: | ---: |",
    ]
    for stage, m in report["latency"].items():
        lines.append(f"| {stage} | {m['calls']} | {m['median_ms']:.2f} | {m['p95_ms']:.2f} |")
    lines += [
        "",
        "## Per-query ranks and eligibility",
        "",
        "Ranks are top-five retrieval ranks. Rejected entries below are expected "
        "hits present in the list but below the cosine gate or missing its dense "
        "lookup. Full per-hit cosine, threshold, placeholder status, context "
        "membership, actual generation context and citation IDs are in JSON.",
        "",
        "| Case | Category | Dense | BM25 | Hybrid | Reranked | Change |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for c in report["cases"]:
        change = c["reranking_change"]["classification"] if c["answerable"] else "not applicable"
        lines.append(
            f"| {c['case_id']} | {c['category']} | "
            + " | ".join(str(c["modes"][m]["rank"] or "—") for m in MODES)
            + f" | {change} |"
        )
    lines += ["", "### Expected evidence rejected by cosine gate", ""]
    for c in report["cases"]:
        for mode, result in c["modes"].items():
            rejected = [
                h
                for h in result["eligibility"]["hits"]
                if h["expected"] and not h["cosine_eligible"]
            ]
            if rejected:
                lines.append(
                    f"- {c['case_id']} / {mode}: "
                    + "; ".join(
                        f"rank {h['rank']}, cosine {h['cosine']}, chunk `{h['chunk_id']}`"
                        for h in rejected
                    )
                    + f". Actual generation context: {result['generation_context_chunk_ids']}; "
                    f"citations: {result['citation_chunk_ids']}."
                )
    lines += ["", "## Automatically identified failure cases", ""]
    for failure in report["failures"]:
        lines.append(
            f"- **{failure['case_id']}** — {failure['query']} " + "; ".join(failure["flags"]) + "."
        )
    lines += ["", "## Limitations", ""] + [f"- {s}" for s in report["limitations"]]
    lines += [
        "",
        "Reproduce from the repository root:",
        "",
        "```bash",
        ".venv/bin/python -m evaluation.run_retrieval_eval",
        "```",
        "",
    ]
    return "\n".join(lines)
