# Evaluation and experiment summary

This page summarizes the completed retrieval and generation experiments. Per-question records, full breakdowns, and methodological caveats remain in the linked reports and `evals/` JSON. The 100-question SEC benchmark is frozen; all retrieval percentages below are measured evidence matching, not semantic answer accuracy.

## Retrieval

The benchmark contains 90 answerable and 10 unanswerable questions. The primary retrieval metric is macro-average Recall@10 over annotated evidence spans with provenance and overlap checks.

| Run | Chunking/system | Recall@10 |
| --- | --- | ---: |
| Dense baseline | Recursive | 42.59% |
| BM25 | SEC section-aware | 67.04% |
| Hybrid RRF | SEC section-aware | **69.26%** |
| BM25 → cross-encoder, depth 20 | SEC section-aware | 67.22% |
| Hybrid → cross-encoder, depth 20 | SEC section-aware | 60.00% |

Section-aware hybrid exceeds the best dense run by 26.67 percentage points, though these are not the same chunk strategy. For a same-strategy comparison, section-aware dense scored 42.04%. The reranker results vary by candidate source/depth and do not justify replacing the default hybrid ranking. Recall@10 can also penalize valid alternative evidence outside the frozen annotation, as documented in the experiment reports.

See [dense retrieval](dense_retrieval.md), [BM25 and hybrid retrieval](lexical_hybrid.md), and [cross-encoder reranking](reranking.md). Machine-readable outputs are under `evals/results/{dense,lexical_hybrid,reranking}/`.

## Grounded generation

The Phase 4B subset contains 20 cases (18 answerable, 2 unanswerable) evaluated with local `qwen3:4b-instruct-2507-q4_K_M`:

- Structured-output validity: 90% (18/20).
- Accepted substantive answers: 8/18 answerable; answerable false-abstention rate: 8/18.
- Unanswerable abstention: 2/2.
- Retrieval failure: 10/18 answerable.
- Citation precision and recall: each 54.17% under the exact-span heuristic.
- Mean latency: 16.9466 seconds (reported as 16.947 seconds).

These counts describe output/heuristic acceptance, not semantic truth. The project does not claim authoritative semantic correctness or faithfulness from lexical overlap. See the [Phase 4B results](phase4b_results.md) and [evaluation methodology](phase4b_generation_evaluation.md).

## Structured financial and agentic validation

The retained Company Facts caches contain 294 accepted facts across three companies and six supported metrics. AAPL FY2025 revenue resolves to 416,161,000,000 USD with SEC concept, period, filing, accession, raw-response hash, and fact pointer. The financial-only demonstration passed. The combined demonstration returned the fact but lacked Apple-specific narrative evidence and failed output validation; the failure was preserved. See the [Phase 5 report](phase5_final_summary.md) and [normalization details](phase5_financial_rebuild.md).

## Observability

Phase 6 imported the saved 20 Phase 4B and four final Phase 5 executions into sanitized traces. Aggregation distinguishes routing, tool execution, evidence sufficiency, output and citation contract status, abstention, taxonomy, latency, and token counts. Fields missing in historical traces remain unavailable. Review [the historical aggregate](../evals/observability/phase6/report.md) and [observability design](phase6_observability.md).
