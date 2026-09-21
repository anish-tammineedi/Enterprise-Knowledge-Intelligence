# Phase 3D: local cross-encoder reranking

## Scope and reproduction

This experiment reranks only section-aware BM25 and hybrid candidates at depths 20 and 50, using the exact existing 1,958 chunks. All 100 questions receive results; the ten unanswerable questions are separated from positive metrics. No generation, agents, financial tools, API serving, or new dependencies are introduced. Earlier benchmark, parsing, chunking, Phase 3B and Phase 3C files remain unchanged, including their documentation.

```bash
.venv/bin/hf download cross-encoder/ms-marco-MiniLM-L6-v2 config.json model.safetensors special_tokens_map.json tokenizer.json tokenizer_config.json vocab.txt --revision 233902d25c440f23af6f7d6e94d2946bac0bee0a --cache-dir data/processed/reranking/models
.venv/bin/python scripts/run_reranking.py
.venv/bin/python -m unittest discover -s tests -v
```

Configuration is in `configs/reranking.json`; the CLI accepts `--root` and `--config`. Only the initial model download needs network access. Existing Sentence Transformers, Torch and NumPy dependencies are sufficient.

## Model and deterministic scoring

Model: [`cross-encoder/ms-marco-MiniLM-L6-v2`](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2), revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`. This Apache-2.0 English passage-ranking model was trained on MS MARCO. Its six layers and approximately 22.7 million parameters make it a practical local baseline; no other reranker was compared. It is not specialized for financial tables.

Inference uses CPU, four Torch threads, batch size 32, seed zero, evaluation mode and deterministic Torch algorithms. Maximum sequence length is 512 tokens for the question/chunk pair including special tokens, with longest-first truncation. Full original chunk text remains in outputs. Pair diagnostics record full input token count, truncation and the encoded chunk end character offset. Raw classifier logits are used without sigmoid; they are ranking scores, not probabilities. Ties use ascending chunk ID. Exact floating-point reproducibility across different hardware/software is not guaranteed; installed versions are part of the cache/run identity.

The candidate generators are the unchanged Phase 3C BM25 and RRF implementations. Existing dense matrices are read without generating embeddings. Candidate top-ten IDs must reproduce the frozen Phase 3C rankings for every query. Candidate pools contain only the source's first 20 or 50 chunks; there is no full-corpus cross-encoder scoring. Both depths share cached scores, and overlapping candidates from the two sources are scored once per question.

## Evaluation and movement definitions

The Phase 3B/3C evidence evaluator is imported unchanged. Matching requires correct source provenance, section membership and exact substring overlap, covering at least 50% of non-whitespace evidence characters and at least 32 characters (or all characters of shorter evidence). Ground truth is used only after ranking.

Recall@K is macro-average evidence recovery across 90 answerable questions. Hit Rate@K requires any matched evidence. Multi-document complete recall averages only the 21 multi-document questions and requires a matched passage from every required document. MRR for reranked results is candidate-limited: a question with no relevant candidate has reciprocal rank zero, while baseline MRR uses the full corpus. Baseline and reranked top-K metrics remain directly comparable for K≤10. All category, difficulty and ticker breakdowns are saved; ticker groups overlap for multi-company questions.

Candidate oracle evidence recall is the fraction of required evidence entries found anywhere in the pool, macro-averaged over questions. Oracle any/all evidence and all-required-document rates are also recorded. These are pool ceilings, not an optimal ordering simulation at a particular K.

At K=10, each missing evidence entry is classified as either absent from the pool or present but missed by the reranker. Question classes are `candidate_generation`, `reranking`, `both`, or `complete`. This prevents treating a missing candidate as a reranking error. A shortfall caused by truncation inside an available chunk remains classified as a reranking limitation.

Promotions into top 1/3/5 and demotions out of top 5 count relevant chunk/query pairs crossing each boundary, compared with that same source's original candidate ranking. Overlapping chunks may support the same evidence, so these are not unique evidence counts. Question improvement/harm/unchanged is reported separately using evidence Recall@5, with additional changes at 1/3/10 saved. All movement lists preserve question and chunk IDs.

The descriptive best configuration is selected by MRR, then Recall@5 and configuration name for failure inspection. Both depths remain reported; this is not a production depth selection. Depth 50 scores 2.5 times as many pairs as depth 20 in an isolated run. No depth-100 diagnostic was needed for this initial two-depth comparison.

## Timing and caching semantics

Pair cache keys include model/config/software signature, full question text, chunk ID and chunk-text hash. Entries include score, diagnostics, checksum and the original measured batch inference time amortized over its pairs. Changing input/model settings invalidates the cache; corrupted entries are recomputed.

Execution logs report actual total wall time, model-load time, measured inference time, per-query joint experiment latency, cache hits and unique pairs inferred. Per-configuration uncached latency estimates sum amortized batch timings from cached pairs. They exclude candidate generation, evaluation and model loading and are estimates rather than independent timing trials. Depth-20 estimates reuse the same batching measurements as depth 50. A cache-only repeat writes a new execution timing log but preserves deterministic ranked results and summaries.

## Overall results

All comparisons below use SEC section-aware chunks. Percentages except MRR. CE20/CE50 mean cross-encoder reranking of the corresponding source pool.

| System | Recall@1 | @3 | @5 | @10 | MRR | Hit@1 | @3 | @5 | @10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dense | 13.33 | 24.81 | 33.70 | 42.04 | 0.2697 | 15.56 | 30.00 | 38.89 | 48.89 |
| BM25 | 18.89 | 35.37 | 43.70 | 67.04 | 0.3714 | 23.33 | 40.00 | 48.89 | 71.11 |
| Hybrid | 15.00 | 39.44 | 50.37 | 69.26 | 0.3513 | 17.78 | 42.22 | 54.44 | 75.56 |
| BM25 → CE20 | 18.89 | 41.11 | 50.56 | 67.22 | 0.3649 | 21.11 | 44.44 | 56.67 | 72.22 |
| BM25 → CE50 | 17.22 | 39.07 | 44.63 | 61.30 | 0.3421 | 20.00 | 43.33 | 50.00 | 66.67 |
| Hybrid → CE20 | 18.33 | 41.67 | 47.04 | 60.00 | 0.3595 | 21.11 | 45.56 | 53.33 | 64.44 |
| Hybrid → CE50 | 18.33 | 37.22 | 45.93 | 55.56 | 0.3463 | 21.11 | 41.11 | 52.22 | 61.11 |

BM25→CE20 has the highest reranked MRR (0.3649), but remains below unreranked BM25 (0.3714). It improves BM25 Recall@3 from 35.37% to 41.11% and Recall@5 from 43.70% to 50.56%, with lower Hit@1 and multi-document completion. Hybrid→CE20 improves hybrid Recall@1/3 and MRR slightly but reduces Recall@5/10. There is no uniform improvement from this reranker.

## Candidate-pool oracle coverage

Evidence recall is macro-averaged over 90 positives; complete-document coverage uses the 21 multi-document questions.

| Pool | Evidence recall | Any evidence | All evidence | All required documents (multi) |
| --- | ---: | ---: | ---: | ---: |
| BM25 → CE20 | 74.81% | 78.89% | 71.11% | 42.86% |
| BM25 → CE50 | 81.48% | 86.67% | 75.56% | 47.62% |
| Hybrid → CE20 | 79.26% | 86.67% | 72.22% | 33.33% |
| Hybrid → CE50 | 87.41% | 92.22% | 82.22% | 61.90% |

Depth 50 increases pool evidence coverage by 6.67 points for BM25 and 8.15 points for hybrid, but lowers final MRR and Recall@5/10 for both. The added candidates include distractors the cross-encoder ranks too highly. It costs approximately 2.5× the isolated inference work. Depth 20 is a lower-cost operating point worth retaining alongside these results; neither depth is selected as a production default solely from benchmark scores.

## Category — recall@5 (%)

| Group | Dense | BM25 | Hybrid | BM25 → CE20 | BM25 → CE50 | Hybrid → CE20 | Hybrid → CE50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ambiguous_adversarial | 25.00 | 30.00 | 35.00 | 30.00 | 35.00 | 35.00 | 35.00 |
| comparative | 10.00 | 23.33 | 20.00 | 25.00 | 5.00 | 5.00 | 5.00 |
| cross_document | 5.00 | 35.00 | 30.00 | 40.00 | 25.00 | 25.00 | 25.00 |
| direct_factual | 40.00 | 60.00 | 70.00 | 70.00 | 70.00 | 70.00 | 70.00 |
| multi_hop | 33.33 | 35.00 | 58.33 | 40.00 | 36.67 | 48.33 | 48.33 |
| numerical | 20.00 | 40.00 | 50.00 | 80.00 | 70.00 | 70.00 | 70.00 |
| section_specific | 60.00 | 60.00 | 70.00 | 50.00 | 40.00 | 40.00 | 40.00 |
| table_oriented | 50.00 | 60.00 | 60.00 | 60.00 | 50.00 | 60.00 | 50.00 |
| temporal | 60.00 | 50.00 | 60.00 | 60.00 | 70.00 | 70.00 | 70.00 |

## Category — recall@10 (%)

| Group | Dense | BM25 | Hybrid | BM25 → CE20 | BM25 → CE50 | Hybrid → CE20 | Hybrid → CE50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ambiguous_adversarial | 30.00 | 50.00 | 55.00 | 55.00 | 55.00 | 45.00 | 55.00 |
| comparative | 15.00 | 38.33 | 40.00 | 40.00 | 35.00 | 15.00 | 20.00 |
| cross_document | 15.00 | 60.00 | 45.00 | 55.00 | 35.00 | 30.00 | 30.00 |
| direct_factual | 50.00 | 90.00 | 90.00 | 90.00 | 80.00 | 80.00 | 70.00 |
| multi_hop | 48.33 | 55.00 | 63.33 | 55.00 | 56.67 | 80.00 | 55.00 |
| numerical | 30.00 | 80.00 | 70.00 | 80.00 | 80.00 | 80.00 | 70.00 |
| section_specific | 60.00 | 80.00 | 80.00 | 80.00 | 70.00 | 60.00 | 60.00 |
| table_oriented | 60.00 | 80.00 | 90.00 | 80.00 | 60.00 | 70.00 | 60.00 |
| temporal | 70.00 | 70.00 | 90.00 | 70.00 | 80.00 | 80.00 | 80.00 |

## Difficulty — recall@5 (%)

| Group | Dense | BM25 | Hybrid | BM25 → CE20 | BM25 → CE50 | Hybrid → CE20 | Hybrid → CE50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| easy | 30.00 | 50.00 | 60.00 | 75.00 | 70.00 | 70.00 | 70.00 |
| hard | 18.33 | 30.83 | 35.83 | 33.75 | 25.42 | 28.33 | 28.33 |
| medium | 56.67 | 56.67 | 63.33 | 56.67 | 53.33 | 56.67 | 53.33 |

## Difficulty — recall@10 (%)

| Group | Dense | BM25 | Hybrid | BM25 → CE20 | BM25 → CE50 | Hybrid → CE20 | Hybrid → CE50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| easy | 40.00 | 85.00 | 80.00 | 85.00 | 80.00 | 80.00 | 70.00 |
| hard | 27.08 | 50.83 | 50.83 | 51.25 | 45.42 | 42.50 | 40.00 |
| medium | 63.33 | 76.67 | 86.67 | 76.67 | 70.00 | 70.00 | 66.67 |

## Ticker — recall@5 (%)

| Group | Dense | BM25 | Hybrid | BM25 → CE20 | BM25 → CE50 | Hybrid → CE20 | Hybrid → CE50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 40.83 | 35.83 | 54.58 | 50.00 | 49.17 | 53.33 | 53.33 |
| MSFT | 30.36 | 54.76 | 44.64 | 50.00 | 41.07 | 42.86 | 39.29 |
| NVDA | 18.18 | 38.89 | 39.39 | 45.45 | 33.33 | 33.33 | 33.33 |

## Ticker — recall@10 (%)

| Group | Dense | BM25 | Hybrid | BM25 → CE20 | BM25 → CE50 | Hybrid → CE20 | Hybrid → CE50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 45.83 | 62.08 | 69.58 | 61.25 | 62.92 | 62.50 | 61.25 |
| MSFT | 48.21 | 63.69 | 62.50 | 71.43 | 55.36 | 57.14 | 53.57 |
| NVDA | 21.21 | 67.68 | 62.12 | 62.12 | 53.03 | 48.48 | 40.91 |

## Multi-document complete recall

Denominator: 21.

| System | @1 | @3 | @5 | @10 | Complete at 10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dense | 0.00% | 0.00% | 0.00% | 4.76% | 1/21 |
| BM25 | 0.00% | 9.52% | 14.29% | 33.33% | 7/21 |
| Hybrid | 0.00% | 9.52% | 14.29% | 23.81% | 5/21 |
| BM25 → CE20 | 0.00% | 4.76% | 9.52% | 28.57% | 6/21 |
| BM25 → CE50 | 0.00% | 0.00% | 0.00% | 19.05% | 4/21 |
| Hybrid → CE20 | 0.00% | 0.00% | 0.00% | 9.52% | 2/21 |
| Hybrid → CE50 | 0.00% | 0.00% | 0.00% | 9.52% | 2/21 |

## Movement and question outcomes

Promotions/demotions count relevant chunk/query pairs. In this run, each counted movement type involved at most one relevant chunk per question, so those counts also equal affected question counts. Question improvement/harm uses Recall@5 relative to the original source.

| Configuration | Into top 1 | Into top 3 | Into top 5 | Out of top 5 | Improved | Harmed | Unchanged |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 → CE20 | 8 | 17 | 19 | 13 | 19 | 12 | 59 |
| BM25 → CE50 | 9 | 18 | 17 | 19 | 16 | 17 | 57 |
| Hybrid → CE20 | 10 | 17 | 12 | 14 | 10 | 14 | 66 |
| Hybrid → CE50 | 10 | 16 | 12 | 16 | 10 | 15 | 65 |

## Failure attribution at ten

Classes are disjoint; candidate-generation and both cases have evidence absent from the pool. Reranking and both cases have available evidence missed at ten. Complete means all evidence recovered.

| Configuration | Candidate only | Reranking only | Both | Complete |
| --- | ---: | ---: | ---: | ---: |
| BM25 → CE20 | 25 | 8 | 1 | 56 |
| BM25 → CE50 | 17 | 18 | 5 | 50 |
| Hybrid → CE20 | 17 | 15 | 8 | 50 |
| Hybrid → CE50 | 11 | 29 | 5 | 45 |

Concrete reranking regressions in BM25→CE20: SEC-021 workforce evidence moves from retrieval rank 6 to reranked rank 15; SEC-075 segment revenue moves from 6 to 16; SEC-100 fiscal-date highlights move from 5 to 11. These relevant chunks are not truncated, so truncation alone does not explain the losses.

## Runtime

Initial execution on local macOS ARM64 CPU (four Torch threads):

- Total experiment wall time: **123.87 seconds**.
- Measured cross-encoder inference: **115.80 seconds**.
- Model load: 2.94 seconds.
- Average joint query wall time: 1.229 seconds; inference alone: 1.158 seconds.
- Actual unique pairs scored: **6,917**, covering 14,000 logical pairs across all four configurations. Only the union of both top-50 pools was inferred.
- Cache-only repeat: **2.39 seconds**, 6,917 cache hits, zero inference, no model load.

| Configuration | Logical pairs | Estimated uncached inference | Estimated per query | Truncated pairs |
| --- | ---: | ---: | ---: | ---: |
| BM25 → CE20 | 2,000 | 33.43s | 0.334s | 353/2000 |
| BM25 → CE50 | 5,000 | 83.64s | 0.836s | 909/5000 |
| Hybrid → CE20 | 2,000 | 33.45s | 0.335s | 410/2000 |
| Hybrid → CE50 | 5,000 | 83.67s | 0.837s | 1085/5000 |

Per-configuration estimates are not production latency guarantees. Cached batch-amortized timings are shared across configurations; summing configuration totals would double-count reused inference. Download time is excluded.

## Ten worst failures of BM25→CE20

Selected by lowest Recall@10, then reciprocal rank, then question ID. All ten have zero recall and no matching evidence in their candidate pool, so they are candidate-generation failures under frozen evidence. This deterministic ordering selects candidate failures before failures with a relevant result below ten; the latter are reported separately above.

| Question | Inspection |
| --- | --- |
| SEC-016 | Actual short Item 8 cross-reference is absent; MD&A references dominate. |
| SEC-018 | Apple decision-maker evidence absent; Microsoft CODM and Apple accounting-policy passages rank highly. |
| SEC-029 | Highlights evidence absent; exact revenue appears in a different end-market table at rank 2. |
| SEC-033 | Correct-year workforce evidence absent; FY2026 workforce is ranked first for a FY2024 question. |
| SEC-034 | Requested Apple FY2024 income statement is absent; unrelated revenue/expense notes appear. |
| SEC-039 | Apple FY2025 repurchase evidence absent; Microsoft and older Apple disclosures appear. |
| SEC-041 | Required workforce passages from both Apple years absent; accounting policies and MD&A dominate. |
| SEC-042 | Employee geography evidence absent; stock-purchase-plan disclosures rank highly. |
| SEC-052 | Required business-description segment anchors absent; alternative MD&A/accounting text appears. |
| SEC-054 | Required original Apple income-statement anchors absent; other years and company expenses dominate. |

## Anomalies and interpretation limits

- Alternative-evidence examples are recorded in `alternative_evidence_review.json`. SEC-029 has the exact requested revenue in a different table at rank 2, outside its highlights anchor. SEC-094 has an alternative correct table at rank 2 but the frozen table already ranks first. No evidence, labels or scoring rules changed.
- Reranking can prefer the wrong year or company: SEC-033 ranks FY2026 workforce first for a FY2024 request, and SEC-039 ranks a Microsoft repurchase passage first for Apple. SEC-100 promotes a stock-performance-graph passage containing dates while demoting the frozen financial highlights to rank 11.
- All first ten worst BM25→CE20 failures are pool misses; this does not imply the cross-encoder has no failures. Eight other questions have reranking-only failure and one has both failure types at ten.
- Pair truncation is material: 17.65%/18.18% of BM25 depth-20/50 pairs and 20.50%/21.70% of hybrid pairs truncate. The full chunk remains the returned object and is used by the unchanged evidence matcher, including text the reranker did not see. Dense candidate generation also retains its documented truncation limitation.
- Frozen evidence is non-exhaustive, and 50% overlap is not semantic answer verification. Broad tables, duplicate disclosures and location-specific questions complicate interpretation. No post-hoc matching changes were made.
- Reranked MRR is computed only over candidates, while original baseline MRR has access to the complete corpus. Candidate oracle coverage and within-pool reciprocal-rank changes are saved so this distinction is inspectable.
- Ten unanswerable questions have separate complete reranked pools per configuration. Scores are not probabilities, and no abstention threshold or negative accuracy is claimed.
- This is one model and two predeclared depths on a small frozen benchmark. MRR-based selection is descriptive, not significance testing or production optimization.

## Validation and file inventory

All 51 tests passed, including every prior test. Repeating the full experiment reused all 6,917 pair scores and left all 15 deterministic experiment result files byte-for-byte and mtime-identical; execution timing is intentionally saved in separate new logs. All protected prior input hashes still match. The benchmark SHA-256 remains `74a2e70d531e389a47730e8c537329ec65cfae5134abec3739a9297feba47e86`.

New source/configuration/documentation files:

- `configs/reranking.json`: pinned model, CPU/batch settings, candidate sources/depths, cache paths and descriptive selection criterion.
- `src/retrieval/reranking.py`: local cross-encoder, raw-logit scoring, pair diagnostics/cache, deterministic sorting and failure/movement analysis.
- `scripts/run_reranking.py`: frozen-artifact validation, candidate reconstruction, alignment checks, experiment CLI, grouped results, oracle/movement summaries and latency logs.
- `tests/test_reranking.py`: four test methods covering ordering, depth enforcement, score alignment/cache invalidation/corruption, provenance, evidence metrics, failure attribution, movement and benchmark immutability.
- `docs/reranking.md`: this report and reproduction instructions.

New generated artifacts:

- `data/processed/reranking/models/`: pinned local model files and Hugging Face cache metadata.
- `data/processed/reranking/scores/`: 6,917 checksummed pair-score JSON entries, including model/input identity, raw score, truncation diagnostics and batch-amortized timing.
- `evals/results/reranking/c4259ce6dabdfc9b/experiment.json`: full configuration, software signature and protected/source hashes.
- Each `bm25_20/`, `bm25_50/`, `hybrid_20/`, `hybrid_50/` directory contains `answerable_results.json` (90 complete reranked pools with metrics/analysis), `unanswerable_results.json` (ten pools), and `summary.json` (all grouped metrics, oracle/movement/failure counts and timing estimates).
- Run-level `summary.json`: original baseline comparisons and all reranked summaries; `worst_failures.json`: selected ten failures with complete inspectable results.
- `executions/*.json`: actual wall/inference/cache timing for each execution, kept separate from deterministic results.
- `alternative_evidence_review.json`: reviewed passages outside frozen evidence; `audit.json`: tests, unchanged-result check, runtime summary and failure-review notes.

No existing files, requirements, benchmark, parsed documents, chunks, Phase 3B artifacts or Phase 3C artifacts were modified. Nothing was committed to Git.
