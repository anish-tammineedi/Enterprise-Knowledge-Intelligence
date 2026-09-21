# Phase 3C: BM25 and hybrid retrieval

## Scope and reproduction

All nine filings and the exact existing 1,555 fixed, 1,850 recursive and 1,958 SEC section-aware chunks are used. The frozen benchmark, chunks, ingestion architecture and Phase 3B files are unchanged. This phase implements lexical ranking and rank fusion only. No new dependencies were necessary: BM25 and RRF use the standard library and existing NumPy.

```bash
.venv/bin/python scripts/run_lexical_hybrid.py
.venv/bin/python -m unittest discover -s tests -v
```

Configuration: `configs/lexical_hybrid.json`; the CLI also accepts `--root` and `--config`. Results: `evals/results/lexical_hybrid/7bc596de695ce349/`. The script requires the saved Phase 3B experiment, loads its aligned query/index matrices, and computes the complete original cosine rankings without loading an embedding model. Each answerable question's recomputed dense metrics must exactly equal Phase 3B or execution fails. No new embeddings or network requests are used.

## Tokenization and BM25

Tokenizer version `sec_conservative_v1` applies Unicode NFKC and case folding, normalizes typographic apostrophes and common nonbreaking hyphens, and retains alphanumeric terms with internal apostrophes, periods and hyphens. Examples: `NVIDIA`, `iPhone`, `CUDA`, `10-K`, `1A`, `FY2026`, `non-GAAP`, `71.1%`. Thousands separators normalize consistently (`133,749` becomes `133749`); decimals and fiscal years remain distinct. Other punctuation is a separator. There is no stemming, lemmatization, stop-word removal, synonym expansion, metadata injection, or numeric magnitude/negation interpretation. Possessives and spelling variants can remain different tokens. Original text is never rewritten.

BM25 sums over distinct query terms, using document term frequency, exact token lengths, and the mean length within each strategy. Parameters are `k1=1.2`, `b=0.75`. Positive IDF is `log(1 + (N - df + 0.5)/(df + 0.5))`; term saturation is `tf*(k1+1)/(tf+k1*(1-b+b*length/average_length))`. These parameters and IDF follow [Lucene's documented defaults](https://lucene.apache.org/core/9_12_1/core/org/apache/lucene/search/similarities/BM25Similarity.html); this implementation uses exact lengths and no Lucene index dependency. Sorted terms and chunk-ID tie breaks make ranking deterministic. Query repetition is binary-weighted rather than repeated as extra votes. No parameters were tuned against results.

## Reciprocal rank fusion

Hybrid score is `1/(constant+dense_rank) + 1/(constant+bm25_rank)` with one-based ranks, equal weights and default `constant=60`, following the established choice in the [original RRF paper](https://cormack.uwaterloo.ca/cormacksigir09-rrf). Raw BM25 and cosine scores are retained for inspection but never added together.

`candidate_depth=null` fuses every chunk from both rankings (1,555–1,958 candidates per retriever). This avoids top-ten candidate censoring and keeps full-ranking MRR comparable. A configurable finite depth must be at least 100; a candidate absent from a truncated list contributes zero from that list. Finite-depth experiments would have candidate-limited MRR and should be labeled accordingly. All ties use ascending deterministic chunk ID. Zero-score BM25 candidates remain in full rankings and can contribute low-rank RRF votes; no query in this run had zero-score BM25 results in its top ten.

## Evaluation policy

The exact Phase 3B evaluator and matching configuration are imported unchanged: document ID, accession, company, ticker, URL, section membership and exact source substring overlap must match; at least 50% of evidence non-whitespace characters and at least 32 characters (or the full shorter evidence) must overlap. Correct filing alone earns no credit.

Recall@K is the macro-average fraction of distinct frozen evidence entries recovered. Hit Rate@K is any evidence recovered. MRR uses the first relevant chunk in the full ranking. Multi-document complete recall requires evidence from every required document and is averaged only over 21 multi-document questions. Complete-evidence recall additionally requires every evidence entry. A 95% union-coverage diagnostic is also preserved.

Positive metrics use 90 questions: 69 single-document, 21 multi-document; 20 easy, 30 medium, 40 hard; ten questions in each of nine positive categories. The ten unanswerable questions are saved separately without positive metrics. Ticker groups include every required ticker, so cross-company questions appear in more than one group. Dense/BM25/hybrid receive only question text; gold provenance is used after ranking.

## Overall results

Recall and hit rates are percentages; MRR is on a 0–1 scale.

| Chunks | System | R@1 | R@3 | R@5 | R@10 | MRR | Hit@1 | Hit@3 | Hit@5 | Hit@10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Fixed | dense | 6.67 | 21.48 | 29.63 | 37.78 | 0.2005 | 7.78 | 25.56 | 36.67 | 45.56 |
| Fixed | bm25 | 18.89 | 37.78 | 46.11 | 62.04 | 0.3559 | 22.22 | 43.33 | 51.11 | 67.78 |
| Fixed | hybrid | 17.78 | 40.56 | 49.44 | 63.70 | 0.3675 | 20.00 | 46.67 | 54.44 | 71.11 |
| Recursive | dense | 11.11 | 20.93 | 28.15 | 42.59 | 0.2307 | 12.22 | 25.56 | 32.22 | 47.78 |
| Recursive | bm25 | 18.89 | 35.93 | 43.70 | 65.37 | 0.3597 | 22.22 | 40.00 | 48.89 | 70.00 |
| Recursive | hybrid | 20.00 | 38.33 | 49.44 | 65.19 | 0.3644 | 22.22 | 40.00 | 52.22 | 70.00 |
| SEC section-aware | dense | 13.33 | 24.81 | 33.70 | 42.04 | 0.2697 | 15.56 | 30.00 | 38.89 | 48.89 |
| SEC section-aware | bm25 | 18.89 | 35.37 | 43.70 | 67.04 | 0.3714 | 23.33 | 40.00 | 48.89 | 71.11 |
| SEC section-aware | hybrid | 15.00 | 39.44 | 50.37 | 69.26 | 0.3513 | 17.78 | 42.22 | 54.44 | 75.56 |

The predeclared selection is highest hybrid Recall@10, then MRR, then strategy name. Section-aware hybrid leads at 69.26%, compared with 67.04% BM25 and 42.04% dense for those chunks. Hybrid is not uniformly better: recursive BM25 has slightly higher Recall@10, and section-aware BM25 has higher MRR (0.3714 versus 0.3513), Recall@1 and multi-document completion. The small benchmark does not establish statistical significance or general superiority.

## Category results

Each cell lists dense / BM25 / hybrid Recall@10 (%). All MRR, hit rates and K values for every group are in summary JSON.

| Group | Fixed | Recursive | SEC section-aware |
| --- | ---: | ---: | ---: |
| ambiguous_adversarial | 25.00 / 50.00 / 60.00 | 25.00 / 50.00 / 40.00 | 30.00 / 50.00 / 55.00 |
| comparative | 23.33 / 28.33 / 35.00 | 20.00 / 38.33 / 40.00 | 15.00 / 38.33 / 40.00 |
| cross_document | 10.00 / 60.00 / 40.00 | 15.00 / 60.00 / 30.00 | 15.00 / 60.00 / 45.00 |
| direct_factual | 30.00 / 90.00 / 90.00 | 60.00 / 90.00 / 80.00 | 50.00 / 90.00 / 90.00 |
| multi_hop | 41.67 / 50.00 / 58.33 | 43.33 / 50.00 / 66.67 | 48.33 / 55.00 / 63.33 |
| numerical | 50.00 / 80.00 / 70.00 | 40.00 / 80.00 / 80.00 | 30.00 / 80.00 / 70.00 |
| section_specific | 40.00 / 60.00 / 60.00 | 40.00 / 80.00 / 70.00 | 60.00 / 80.00 / 80.00 |
| table_oriented | 50.00 / 70.00 / 70.00 | 50.00 / 70.00 / 90.00 | 60.00 / 80.00 / 90.00 |
| temporal | 70.00 / 70.00 / 90.00 | 90.00 / 70.00 / 90.00 | 70.00 / 70.00 / 90.00 |

## Difficulty results

Each cell lists dense / BM25 / hybrid Recall@10 (%). All MRR, hit rates and K values for every group are in summary JSON.

| Group | Fixed | Recursive | SEC section-aware |
| --- | ---: | ---: | ---: |
| easy | 40.00 / 85.00 / 80.00 | 50.00 / 85.00 / 80.00 | 40.00 / 85.00 / 80.00 |
| hard | 25.00 / 47.08 / 48.33 | 25.83 / 49.58 / 44.17 | 27.08 / 50.83 / 50.83 |
| medium | 53.33 / 66.67 / 73.33 | 60.00 / 73.33 / 83.33 | 63.33 / 76.67 / 86.67 |

## Ticker results

Each cell lists dense / BM25 / hybrid Recall@10 (%). All MRR, hit rates and K values for every group are in summary JSON.

| Group | Fixed | Recursive | SEC section-aware |
| --- | ---: | ---: | ---: |
| AAPL | 37.50 / 55.83 / 55.83 | 49.58 / 59.58 / 64.17 | 45.83 / 62.08 / 69.58 |
| MSFT | 54.76 / 69.05 / 71.43 | 46.43 / 61.90 / 55.36 | 48.21 / 63.69 / 62.50 |
| NVDA | 16.16 / 58.59 / 53.03 | 18.18 / 67.68 / 60.61 | 21.21 / 67.68 / 62.12 |

## Multi-document complete recall

Percentages, denominator 21. A matching company alone does not recover a document.

| Chunks | System | @1 | @3 | @5 | @10 | Complete at 10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Fixed | dense | 0.00 | 0.00 | 0.00 | 0.00 | 0/21 |
| Fixed | bm25 | 0.00 | 4.76 | 14.29 | 23.81 | 5/21 |
| Fixed | hybrid | 0.00 | 4.76 | 23.81 | 23.81 | 5/21 |
| Recursive | dense | 0.00 | 0.00 | 0.00 | 9.52 | 2/21 |
| Recursive | bm25 | 0.00 | 14.29 | 14.29 | 33.33 | 7/21 |
| Recursive | hybrid | 0.00 | 14.29 | 14.29 | 19.05 | 4/21 |
| SEC section-aware | dense | 0.00 | 0.00 | 0.00 | 4.76 | 1/21 |
| SEC section-aware | bm25 | 0.00 | 9.52 | 14.29 | 33.33 | 7/21 |
| SEC section-aware | hybrid | 0.00 | 9.52 | 14.29 | 23.81 | 5/21 |

## Complementarity

Solved means **every required frozen evidence entry recovered at ten**, not merely one hit. Missed means not completely solved and can include partial recovery. The groups below are not an exhaustive disjoint partition: the first two compare standalone systems irrespective of hybrid performance. JSON also records question-level evidence set differences and zero-evidence misses.

| Chunks | Dense solved, BM25 missed | BM25 solved, dense missed | Hybrid only | Missed by all | Standalone solved, hybrid missed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed | 5 | 29 | 6 | 28 | 11 |
| Recursive | 6 | 27 | 3 | 26 | 10 |
| SEC section-aware | 4 | 29 | 4 | 25 | 8 |

For section-aware chunks, dense uniquely recovers Apple repurchases, Services growth and gross-margin disclosures (SEC-039/062/077/093). BM25 uniquely recovers foundry names, acquisition/product names, and several numeric/version distinctions. Hybrid-only cases are SEC-010 (Microsoft segments), SEC-030 (NVIDIA revenue growth), SEC-033 (NVIDIA workforce countries in the correct year), and SEC-045 (Apple payment services plus NVIDIA game streaming). Fusion also loses eight questions solved by a standalone system.

### Fixed question IDs

- **dense_not_bm25:** SEC-038, SEC-039, SEC-077, SEC-079, SEC-093

- **bm25_not_dense:** SEC-001, SEC-002, SEC-004, SEC-005, SEC-006, SEC-009, SEC-011, SEC-020, SEC-023, SEC-026, SEC-030, SEC-034, SEC-037, SEC-043, SEC-044, SEC-047, SEC-050, SEC-060, SEC-063, SEC-066, SEC-067, SEC-073, SEC-074, SEC-075, SEC-076, SEC-094, SEC-095, SEC-097, SEC-100

- **hybrid_only:** SEC-012, SEC-014, SEC-033, SEC-058, SEC-091, SEC-099

- **missed_by_all:** SEC-008, SEC-016, SEC-018, SEC-021, SEC-029, SEC-041, SEC-042, SEC-045, SEC-046, SEC-048, SEC-049, SEC-051, SEC-052, SEC-053, SEC-054, SEC-055, SEC-056, SEC-057, SEC-059, SEC-061, SEC-062, SEC-064, SEC-068, SEC-069, SEC-070, SEC-072, SEC-092, SEC-098

### Recursive question IDs

- **dense_not_bm25:** SEC-034, SEC-039, SEC-054, SEC-062, SEC-077, SEC-093

- **bm25_not_dense:** SEC-004, SEC-006, SEC-007, SEC-012, SEC-014, SEC-015, SEC-020, SEC-021, SEC-023, SEC-026, SEC-027, SEC-043, SEC-044, SEC-047, SEC-055, SEC-059, SEC-060, SEC-061, SEC-063, SEC-067, SEC-075, SEC-076, SEC-079, SEC-094, SEC-095, SEC-096, SEC-100

- **hybrid_only:** SEC-030, SEC-033, SEC-072

- **missed_by_all:** SEC-010, SEC-016, SEC-018, SEC-029, SEC-041, SEC-042, SEC-045, SEC-046, SEC-048, SEC-049, SEC-051, SEC-052, SEC-053, SEC-056, SEC-057, SEC-058, SEC-064, SEC-066, SEC-068, SEC-069, SEC-070, SEC-074, SEC-091, SEC-092, SEC-098, SEC-099

### SEC section-aware question IDs

- **dense_not_bm25:** SEC-039, SEC-062, SEC-077, SEC-093

- **bm25_not_dense:** SEC-004, SEC-006, SEC-007, SEC-009, SEC-014, SEC-015, SEC-021, SEC-023, SEC-024, SEC-026, SEC-027, SEC-036, SEC-043, SEC-044, SEC-050, SEC-055, SEC-059, SEC-060, SEC-061, SEC-063, SEC-064, SEC-067, SEC-075, SEC-076, SEC-079, SEC-094, SEC-095, SEC-096, SEC-100

- **hybrid_only:** SEC-010, SEC-030, SEC-033, SEC-045

- **missed_by_all:** SEC-016, SEC-018, SEC-029, SEC-034, SEC-041, SEC-042, SEC-046, SEC-048, SEC-049, SEC-051, SEC-052, SEC-053, SEC-054, SEC-056, SEC-057, SEC-058, SEC-066, SEC-068, SEC-069, SEC-070, SEC-074, SEC-091, SEC-092, SEC-098, SEC-099

## Ten worst hybrid failures

Best hybrid configuration: section-aware, RRF constant 60, complete candidate rankings. Sort: lowest Recall@10, lowest reciprocal rank, then question ID. All ten have zero frozen-evidence recall at ten.

| Question | First matching rank | Inspection |
| --- | ---: | --- |
| SEC-018 | 379 | Apple FY2025 decision maker: accounting policies and financial-note page furniture outrank the specific segment disclosure. |
| SEC-069 | 218 | NVIDIA FY2025 Item 8 / net income: MD&A and other years outrank the required cross-reference and statement. |
| SEC-092 | 193 | NVIDIA income-statement location: forward-looking text and preamble material outrank the Item cross-reference. |
| SEC-052 | 184 | Apple versus Microsoft segments: accounting policies and Microsoft MD&A displace the required business-description anchors. |
| SEC-016 | 153 | NVIDIA Item 8 cross-reference: MD&A references and exhibit text outrank the short actual Item 8. |
| SEC-041 | 148 | Apple workforce across years: financial-note page furniture outranks human-capital evidence. |
| SEC-029 | 95 | NVIDIA FY2026 revenue: the exact value is present at rank 2 in an alternative table, but the frozen highlights evidence ranks 95. |
| SEC-042 | 50 | Microsoft employee geography across years: employee stock plans and NVIDIA tax tables displace workforce counts. |
| SEC-056 | 50 | Apple/NVIDIA manufacturing comparison: generic MD&A references to Item 1A dominate over manufacturing evidence. |
| SEC-091 | 38 | Apple/Intelligent Cloud false premise: Microsoft segment disclosures dominate the ranking. |

## Interpretation and suspicious behavior

- **Numerical:** BM25 reaches 80% Recall@10 across all strategies. Hybrid is 70/80/70%. Full lexical access to numbers complements embeddings, but fusion can demote a useful exact match; this is not evidence that all numeric questions are solved.
- **Versions:** hybrid reaches 90% temporal Recall@10 for every strategy, versus BM25's 70%. Repeated years in comparative financial tables still cause distractors. No hard fiscal-year filtering is applied.
- **Names:** BM25 solves section-aware SEC-004/007/009 where dense does not (foundries, acquisition, product operating system). SEC-091 still favors Microsoft's Intelligent Cloud over Apple's actual segments because the adversarial premise contains a strong competing name.
- **SEC Items:** Item labels in cross-references and page furniture do not imply evidence relevance. Short NVIDIA Item 8 cross-references remain difficult (SEC-016/069/092). The unchanged evaluator prevents company/Item mentions alone from earning credit.
- **Multiple documents:** BM25 complete recall at ten is 5/21, 7/21, 7/21 versus hybrid 5/21, 4/21, 5/21. RRF does not explicitly enforce diversity or document coverage. Dense evidence can dilute good lexical ranks.
- **Alternative evidence:** SEC-029 retrieves the exact NVIDIA revenue at hybrid rank 2 in a different table, but the requested highlights evidence ranks 95. SEC-094 has alternative correct GAAP income at rank 1 and the frozen evidence at rank 4. SEC-100 retrieves calendar/date material outside the frozen evidence. Inspectable cases are saved separately in `alternative_evidence_review.json`; none change scores or gold labels.
- **Overlap policy:** the inherited 50% overlap rule is a retrieval-location proxy, not a proof of answer sufficiency; broad tables can match without the requested row, and adequate short passages can fail. The existing strict union metric is retained for inspection without changing the primary selection rule.
- **Truncation:** BM25 reads entire chunks, including tails omitted by the 512-token dense model. The Phase 3B truncation counts (300 fixed, 228 recursive, 223 section-aware) remain relevant and confound attribution of gains purely to lexical matching.
- **Preprocessing:** exact terms retain inflection/possessive/hyphenation differences. Punctuation removal is not accounting interpretation and does not preserve the meaning of parentheses as negative amounts. No post-result tokenization tuning was done.
- **Full ranking:** zero BM25 scores are retained with deterministic ties and can add weak RRF votes. No BM25 top-ten result had zero score in this run. Empty/OOV query behavior is tested; tie-driven low-rank MRR should not be interpreted as strong retrieval.
- **Unanswerables:** all ten have separate results per system/strategy. Raw score ranges in `audit.json` are inspection data, not calibrated probabilities or an abstention evaluation. Dense/BM25/RRF scores are not mutually comparable.

## Validation and files

All 47 tests passed, including all 41 previous tests. A full repeat run preserved bytes and modification times for all 31 generated experiment files. Two subsequent review/audit files bring the run directory to 33 files. Every dense per-question metric exactly reproduced Phase 3B. Input hashes are checked before and after the run. Benchmark SHA-256 remains `74a2e70d531e389a47730e8c537329ec65cfae5134abec3739a9297feba47e86`.

Created:

- `src/retrieval/lexical.py`: conservative tokenizer, BM25 postings/scoring, deterministic RRF.
- `configs/lexical_hybrid.json`: BM25 and fusion settings, existing dense run, output path and comparison definitions.
- `scripts/run_lexical_hybrid.py`: validates inputs/embedding alignment, reconstructs dense rankings, runs BM25/fusion, reuses unchanged evaluation, saves grouped results, computes complementarity and selects worst failures.
- `tests/test_lexical_hybrid.py`: six tests covering token preservation, hand-calculated BM25 scores, empty queries/ties, RRF arithmetic/depth, frozen evidence/metrics, benchmark immutability and complementarity.
- `docs/lexical_hybrid.md`: this method, results and failure-review report.
- Run-level `experiment.json`: configuration, inherited dense policy, source/input hashes and NumPy version.
- For each of nine strategy/system pairs, `answerable_results.json`, `unanswerable_results.json`, and `summary.json`: top-ten chunks with full text/provenance, both component ranks/scores, system score, evidence matches, first relevant result even beyond ten, and full grouped metrics.
- Run-level `summary.json`: consolidated comparisons and validation status.
- Run-level `complementarity.json`: question IDs in every comparison group and per-question evidence differences.
- Run-level `worst_hybrid_failures.json`: ten selected failures with complete inspectable results.
- Run-level `alternative_evidence_review.json`: separate review notes and source chunks for three alternative-evidence cases.
- Run-level `audit.json`: repeat-run validation, test count, negative score ranges and failure notes.

Changed:

- `README.md`: adds Phase 3C usage and a link to this report.

No dependency, benchmark, ingestion, chunking, or Phase 3B source/output files were changed. No commits were made.
