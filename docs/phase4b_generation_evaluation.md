# Phase 4B generation evaluation methodology

Phase 4B evaluated a deterministic 20-question representative subset after the approved local Qwen generation run. This page describes selection and scoring; the [results report](phase4b_results.md) and machine-readable [results](../evals/generation/phase4b/results.json) are authoritative for outcomes.

## Subset construction

The 20-question subset selects two questions per benchmark category using `scripts/build_phase4b_subset.py`. Categories are processed lexicographically; within each category, the lowest question IDs are chosen across available easy, medium, and hard difficulty levels, then the lowest remaining ID. Selection does not depend on model outputs or retrieval scores. The saved subset includes 18 answerable and two unanswerable questions.

The run reused four Phase 4A traces and generated the remaining 16 outputs with the local `qwen3:4b-instruct-2507-q4_K_M` model. Raw outputs and per-question attribution remain in the Phase 4A trace directory and Phase 4B results. This page does not authorize or perform a generation rerun.

## Metrics and attribution

The provider-independent evaluator in `src/evaluation/generation_metrics.py` measures structured-output validity, citation-contract validity, citation precision/recall against frozen evidence spans, retrieval evidence presence, abstention rates, latency, token use, and lexical-overlap screening heuristics. Citation precision/recall are exact-span proxies. Answer correctness and groundedness overlap heuristics do not establish semantic correctness or faithfulness; no authoritative semantic score is claimed.

Primary failure attribution distinguishes retrieval failure, generation failure, citation failure, expected abstention, invalid structured output, and successful grounded answer. A retrieval failure means no supplied context overlaps the benchmark's annotated evidence under the frozen matcher. Full methodology, limitations, and measured outcomes are in the [Phase 4B results report](phase4b_results.md).
