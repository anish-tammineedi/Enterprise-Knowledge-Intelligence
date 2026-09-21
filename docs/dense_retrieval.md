# Phase 3B: dense retrieval baseline

## Scope and reproduction

This experiment uses all nine frozen parsed filings and all existing chunks. The benchmark, parsed documents, ingestion code, and chunking code/content were not changed. No lexical retrieval, hybrid retrieval, reranking, answer generation, or agents are implemented.

The single model is [`BAAI/bge-small-en-v1.5`](https://huggingface.co/BAAI/bge-small-en-v1.5), an MIT-licensed English general-purpose embedding model with 384 dimensions and a 512-token input limit. Its small size makes local CPU experiments practical. This is a baseline choice, not a model comparison or a claim of financial-domain suitability. Revision is pinned to `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`. Queries use the model card's retrieval instruction; documents contain only existing chunk text, with no added metadata or gold information.

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/hf download BAAI/bge-small-en-v1.5 config.json config_sentence_transformers.json sentence_bert_config.json modules.json 1_Pooling/config.json tokenizer.json tokenizer_config.json special_tokens_map.json vocab.txt model.safetensors --revision 5c38ec7c405ec4b44b94cc5a9bb96e735b38267a --cache-dir data/processed/dense/models
.venv/bin/python scripts/run_dense_retrieval.py
.venv/bin/python -m unittest discover -s tests -v
```

Only model installation requires network access. Experiment execution loads the local snapshot. Configuration is in `configs/dense_retrieval.json`; CLI accepts `--root` and `--config`. Observed versions: sentence-transformers 5.7.0, transformers 5.17.0, torch 2.14.0, numpy 2.5.3. CPU, four threads, seed zero, evaluation mode, and deterministic Torch algorithms are configured. Exact reproducibility across hardware/library changes is not promised; versions enter cache and experiment identities.

## Matching and metric definitions

All chunks in each strategy are ranked independently by cosine similarity. Ties use ascending chunk ID. No company/year/section filtering uses benchmark metadata. Ground truth is consulted only after ranking.

A relevant chunk must match document ID, accession, ticker, company, URL, and evidence section membership. Its character overlap must exactly match the frozen source substring, cover at least 50% of the evidence's non-whitespace characters, and contain at least 32 such characters (or all characters for evidence shorter than 32). Matching company or filing alone earns no credit. These thresholds are explicit experiment configuration, set before the comparison.

- **Recall@K:** fraction of distinct required evidence entries matched by at least one top-K chunk, macro-averaged over questions. This is evidence recall, not a count of overlapping relevant chunks.
- **Hit Rate@K:** fraction of questions with at least one matched evidence entry in top K.
- **MRR:** mean reciprocal rank of the first matching chunk across the full index, not capped at ten. The first relevant result is saved even when it ranks below ten.
- **Multi-document complete recall@K:** fraction of the 21 multi-document questions where every required document has at least one evidence-matching chunk. This differs from recovering every evidence entry.
- **Complete evidence@K:** all required evidence entries matched.
- **Strict union recall@K:** diagnostic evidence recall requiring 95% coverage by the union of top-K source spans. Overlapping characters count once.

Positive metrics use 90 questions: 69 single-document and 21 multi-document. Ten unanswerable questions have separate ranked result files and no positive recall/MRR. Each of nine positive categories has ten questions; positive difficulty counts are 20 easy, 30 medium, 40 hard. The tenth category is unanswerable. Ticker groups include every question requiring that ticker and therefore overlap for cross-company questions.

## Overall results

Percentages below apply to recall and hit rate; MRR is on a 0–1 scale.

| Strategy | Chunks | R@1 | R@3 | R@5 | R@10 | MRR | Hit@1 | Hit@3 | Hit@5 | Hit@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed | 1,555 | 6.67 | 21.48 | 29.63 | 37.78 | 0.2005 | 7.78 | 25.56 | 36.67 | 45.56 |
| Recursive | 1,850 | 11.11 | 20.93 | 28.15 | 42.59 | 0.2307 | 12.22 | 25.56 | 32.22 | 47.78 |
| SEC section-aware | 1,958 | 13.33 | 24.81 | 33.70 | 42.04 | 0.2697 | 15.56 | 30.00 | 38.89 | 48.89 |

The predeclared selection rule is highest Recall@10, then MRR, then strategy name. Recursive leads Recall@10 by 0.56 percentage points over section-aware; section-aware leads MRR and Recall@1/3/5. These measurements do not establish general superiority or statistical significance.

## Results by category

Each cell is Recall@10 (%) / MRR. All K values and other metrics are saved in JSON.

| Group | Questions | Fixed | Recursive | SEC section-aware |
| --- | ---: | ---: | ---: | ---: |
| ambiguous_adversarial | 10 | 25.00 / 0.0660 | 25.00 / 0.2257 | 30.00 / 0.3327 |
| comparative | 10 | 23.33 / 0.2466 | 20.00 / 0.1078 | 15.00 / 0.1709 |
| cross_document | 10 | 10.00 / 0.1016 | 15.00 / 0.0791 | 15.00 / 0.0673 |
| direct_factual | 10 | 30.00 / 0.2030 | 60.00 / 0.2083 | 50.00 / 0.2065 |
| multi_hop | 10 | 41.67 / 0.2408 | 43.33 / 0.3712 | 48.33 / 0.4162 |
| numerical | 10 | 50.00 / 0.1208 | 40.00 / 0.1682 | 30.00 / 0.1883 |
| section_specific | 10 | 40.00 / 0.2254 | 40.00 / 0.2077 | 60.00 / 0.2805 |
| table_oriented | 10 | 50.00 / 0.3608 | 50.00 / 0.3286 | 60.00 / 0.4657 |
| temporal | 10 | 70.00 / 0.2400 | 90.00 / 0.3795 | 70.00 / 0.2991 |

## Results by difficulty

Each cell is Recall@10 (%) / MRR. All K values and other metrics are saved in JSON.

| Group | Questions | Fixed | Recursive | SEC section-aware |
| --- | ---: | ---: | ---: | ---: |
| easy | 20 | 40.00 / 0.1619 | 50.00 / 0.1883 | 40.00 / 0.1974 |
| hard | 40 | 25.00 / 0.1637 | 25.83 / 0.1959 | 27.08 / 0.2468 |
| medium | 30 | 53.33 / 0.2754 | 60.00 / 0.3052 | 63.33 / 0.3484 |

## Results by ticker

Each cell is Recall@10 (%) / MRR. All K values and other metrics are saved in JSON.

| Group | Questions | Fixed | Recursive | SEC section-aware |
| --- | ---: | ---: | ---: | ---: |
| AAPL | 40 | 37.50 / 0.2059 | 49.58 / 0.2272 | 45.83 / 0.3365 |
| MSFT | 28 | 54.76 / 0.2734 | 46.43 / 0.3140 | 48.21 / 0.2668 |
| NVDA | 33 | 16.16 / 0.1256 | 18.18 / 0.0980 | 21.21 / 0.1199 |

## Multi-document complete recall

Denominator: 21 questions. Recovery requires evidence from every required document.

| Strategy | @1 | @3 | @5 | @10 | Complete at 10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed | 0.00% | 0.00% | 0.00% | 0.00% | 0/21 |
| Recursive | 0.00% | 0.00% | 0.00% | 9.52% | 2/21 |
| SEC section-aware | 0.00% | 0.00% | 0.00% | 4.76% | 1/21 |

## Ten worst recursive results

Ordered by lowest Recall@10, then lowest reciprocal rank, then question ID. All ten have zero frozen-evidence recall at ten. Alternative evidence can make this different from answerability of the retrieved text.

| ID | First frozen-evidence match rank | Inspection |
| --- | ---: | --- |
| SEC-016 | 585 | NVIDIA FY2025 Item 8 cross-reference: higher ranks favor business/investor information and other years. |
| SEC-100 | 388 | NVIDIA FY2026 fiscal year-end: rank 1 has the date in a deferred-revenue table and rank 3 describes the fiscal calendar, outside the frozen highlights-table evidence. Potential evidence-anchor false negative. |
| SEC-057 | 387 | Apple 2023 versus 2024 cybersecurity disclosures: top ranks favor MD&A/product introductions rather than the required Items. |
| SEC-029 | 363 | NVIDIA FY2026 revenue: top ranks favor deferred-revenue/other-asset tables and other years. |
| SEC-056 | 330 | Apple outsourcing versus NVIDIA fabless manufacturing: required manufacturing evidence is displaced by unrelated introductions and financial notes. |
| SEC-094 | 251 | Microsoft FY2026 GAAP net income: rank 1 contains only the adjusted-income tail of the gold table. Rank 4 contains the correct GAAP value in a different reconciliation table, a confirmed alternative-evidence false negative under the frozen anchors. |
| SEC-018 | 221 | Apple FY2025 chief operating decision maker: product and MD&A material outranks the segment note. |
| SEC-091 | 203 | Apple/Intelligent Cloud false premise: Microsoft segment terminology attracts rank 1; required Apple segment evidence is absent. |
| SEC-098 | 195 | Apple FY2023 cybersecurity Item versus risk disclosure: other years and sections dominate. |
| SEC-004 | 182 | NVIDIA FY2026 wafer foundries: financial segment tables outrank manufacturing evidence. Direct re-encoding verified saved vector alignment; this is a measured ranking failure. |

## Limitations and audit findings

- Frozen evidence anchors are not exhaustive. SEC-094 has a confirmed correct alternative table at recursive rank 4 that earns no credit. SEC-100 retrieves fiscal-calendar/date material outside its annotated highlights table. These are review findings only; gold evidence and scoring were not revised.
- A 50% span match measures substantial overlap, not semantic answer completeness. A broad table may overlap while omitting the requested row; conversely, a sufficient short row may fail the threshold. Table delimiters count as non-whitespace. Strict union recall exposes some sensitivity but does not resolve semantic equivalence.
- Strict union Recall@10 is 29.26% fixed, 37.78% recursive, 40.37% section-aware, which changes the strategy ordering relative to primary Recall@10. The primary selection criterion was retained.
- All 90 positive questions have all evidence entries matchable somewhere in each complete index. Low top-K scores are not caused by wholly unmatchable evidence under this policy.
- Repeated disclosures and wrong-year/company results occupy ranks, with very low multi-document completion. Numerical and fiscal-year terms alone do not reliably distinguish the required disclosure.
- The model truncates inputs beyond 512 tokens without changing saved chunk text. Truncated chunks: 300/1,555 fixed (19.29%), 228/1,850 recursive (12.32%), 223/1,958 section-aware (11.39%). No queries truncate. Each index/result records full input token count and encoded text end offset. Evaluation concerns the full returned chunk, including any tail not represented by the embedding. This is a material confound for chunking comparison; no input rechunking was performed.
- Unexpected SEC-004 rankings were checked by re-encoding the query and two chunks. Maximum sampled vector difference was below 1.5e-7, consistent with floating-point batching differences rather than misalignment.
- Unanswerable top-1 cosine scores are recorded in `audit.json`. Scores are not calibrated probabilities; no abstention threshold or unanswerable accuracy is claimed.

## Validation and immutability

All 41 tests passed, including the 33 existing tests and eight new dense retrieval tests. A full repeat run had 5,463 cache hits and zero misses; all 20 experiment outputs retained identical bytes and modification times. The subsequently added audit file records these checks. Benchmark SHA-256 remains `74a2e70d531e389a47730e8c537329ec65cfae5134abec3739a9297feba47e86`. Input hashes are checked before and after execution; source slices, provenance, deterministic chunk IDs and parsed-document hashes are validated before indexing.

## Files created or changed

- `configs/dense_retrieval.json`: model revision, input/output paths, batch settings, matching policy, K values, selection rule.
- `src/embeddings/local_dense.py`: local Sentence Transformers encoder, tokenization diagnostics, checksummed per-record cache, deterministic JSON/array writes. Cache identity includes model/library/config signature, role, ID and text hash; unchanged records are reused and corrupt vectors recomputed.
- `src/retrieval/dense.py`: cosine ranking with deterministic ties and input validation.
- `src/evaluation/dense_metrics.py`: provenance/offset matching, union coverage, positive and multi-document metrics, category/difficulty/ticker aggregation.
- `scripts/run_dense_retrieval.py`: CLI, frozen-input validation, independent indexes, cached query embeddings, ranked results and summaries.
- `tests/test_dense_retrieval.py`: cache reuse/invalidation/corruption, alignment, cosine, evidence overlap, union deduplication, multi-document metrics, full-ranking MRR, negative exclusion and immutable corpus checks.
- `requirements.txt`: adds NumPy, Sentence Transformers and Torch; retains existing dependencies.
- `README.md`: links this phase and reproduction command.
- `docs/dense_retrieval.md`: this construction, execution, results and limitations guide.
- `data/processed/dense/models/`: downloaded pinned model snapshot and Hugging Face cache metadata.
- `data/processed/dense/embeddings/`: 5,463 per-record vectors with checksummed identity/diagnostic JSON sidecars, separated by strategy/query namespace.
- `evals/results/dense/3deb29d60b899b2a/experiment.json`: full experiment configuration, model/software signature and protected input hashes.
- `query_embeddings.npy` and `query_manifest.json` in that run: 100 query vectors with deterministic row mappings and diagnostics.
- Each of `fixed_size/`, `recursive/`, `sec_section/` in that run contains `embeddings.npy` (index matrix), `index_manifest.json` (complete chunk text/provenance and row alignment), `answerable_results.json` (90 queries, top ten plus first evidence hit), `unanswerable_results.json` (ten queries, top ten), and `summary.json` (all aggregate/grouped metrics and diagnostics).
- Run-level `summary.json`: consolidated metrics and unchanged-input status; `worst_failures.json`: deterministic ten-failure selection including inspectable chunks; `audit.json`: repeat-run checks, sampled alignment check, failure review and negative-score ranges.

Every ranked chunk retains original metadata and text, with rank, similarity, filing/report years, matching evidence IDs and embedding diagnostics added. Nothing was committed to Git.
