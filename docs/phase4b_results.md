# Phase 4B representative grounded-generation evaluation

This report evaluates the approved 20-question subset using the frozen benchmark, existing SEC section-aware BM25 top-five retrieval, the unchanged grounded prompt/configuration, and `qwen3:4b-instruct-2507-q4_K_M` at digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`. Four Phase 4A traces were reused; 16 new local Ollama calls were made. No paid calls or model downloads occurred.

## Aggregate results

| Metric | Result |
|---|---:|
| Questions (answerable / unanswerable) | 20 (18 / 2) |
| Structured-output validity | 90.00% (18/20) |
| Accepted substantive answer rate (answerable) | 44.44% (8/18) |
| Answerable false-abstention rate | 44.44% (8/18) |
| Unanswerable abstention rate | 100.00% (2/2) |
| Citation validity (valid traces) | 100.00% (18/18) |
| Citation precision (deterministic span heuristic) | 54.17% |
| Citation recall (deterministic span heuristic) | 54.17% |
| Retrieval failures | 10/20 (50.00%); 10/18 answerable |
| Generation failures | 5/20 (25.00%) |
| Citation failures | 1/20 (5.00%) |
| Invalid structured output | 2/20 (10.00%) |
| Expected abstentions | 2/20 (10.00%) |
| Successful grounded answers | 0/20 under the conservative heuristic |
| Mean / median latency | 16.947 s / 15.720 s |
| Input / output / total tokens | 91,945 / 1,577 / 93,522 |

The answer rate counts valid non-abstaining outputs, regardless of semantic correctness. Correctness and groundedness are token-overlap screening heuristics, not authoritative semantic judgments; manual or judge evaluation is required for those metrics.

## Attribution by category

| Category | Questions | Attribution counts |
|---|---:|---|
| ambiguous_adversarial | 2 | retrieval 2 |
| comparative | 2 | generation 1, retrieval 1 |
| cross_document | 2 | retrieval 2 |
| direct_factual | 2 | generation 1, retrieval 1 |
| multi_hop | 2 | invalid output 1, retrieval 1 |
| numerical | 2 | generation 1, retrieval 1 |
| section_specific | 2 | generation 1, retrieval 1 |
| table_oriented | 2 | generation 1, retrieval 1 |
| temporal | 2 | citation 1, invalid output 1 |
| unanswerable | 2 | expected abstention 2 |

## Attribution by difficulty

| Difficulty | Questions | Attribution counts |
|---|---:|---|
| easy | 4 | generation 2, retrieval 2 |
| medium | 8 | generation 2, citation 1, invalid output 1, retrieval 2, expected abstention 2 |
| hard | 8 | generation 1, invalid output 1, retrieval 6 |

## Failed questions

Every original model output remains unchanged in `evals/generation/phase4a_ollama/traces/`; the machine-readable results retain the raw output as well. Retrieval failures mean no supplied top-five context met the frozen exact-span overlap policy. Generation failures mean evidence was available but the response abstained or failed the conservative answer check. Citation failure means the answer/citation relationship was invalid. SEC-061 and SEC-032 are invalid structured outputs; they were not repaired.

## Findings

Retrieval is the dominant measured bottleneck: half of all subset cases, and 10 of 18 answerable cases, lacked an exact evidence match in the supplied context. The model also produced substantial generation errors when evidence was present. Citation membership validation was strong for accepted traces, but citation precision/recall were only 54.17% under exact-span heuristics. Both unanswerable cases abstained correctly. Semantic correctness and faithfulness remain unresolved by deterministic checks and require Phase 4B adjudication work if formal answer-quality claims are needed.

Machine-readable results, raw outputs, category/difficulty breakdowns, latency and token totals are in [results.json](../evals/generation/phase4b/results.json). The benchmark and protected artifacts were hash-verified after evaluation.
