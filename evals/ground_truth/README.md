# SEC retrieval benchmark — Phase 3A

## Files and commands

- `sec_retrieval_benchmark.json`: 100 questions, expected answers, exact supporting spans, source manifest, and negative-case explanations.
- `validation_report.json`: deterministic validation results and distribution counts; no retrieval scores.
- `README.md`: construction method, schema, category definitions, distributions, and review caveats.

From the repository root:

```bash
.venv/bin/python scripts/validate_retrieval_benchmark.py --report evals/ground_truth/validation_report.json
.venv/bin/python -m unittest discover -s tests -v
```

The validator also accepts `--root` and `--benchmark`. A failure returns a nonzero exit code. An unchanged validation report is not rewritten. No additional dependencies are needed.

## Construction

This benchmark was constructed before retrieval implementation. Each question was individually authored after inspecting the actual parsed passages and financial tables in `data/processed/parsed/`. There was no template expansion, chunk sampling, retriever output, embedding model, external answer source, or model-generation pipeline. A temporary authoring utility copied the manually selected source spans and metadata into the final static JSON; it did not generate questions. The benchmark operates on the provided corpus as its authority and does not independently authenticate filings against EDGAR.

The corpus contains Apple fiscal 2023–2025, Microsoft fiscal 2024–2026, and NVIDIA fiscal 2024–2026 filings. Inspections covered business descriptions, workforce disclosures, manufacturing dependencies, cybersecurity, capital returns, remaining performance obligations, segment changes, financial statements, and financial tables. Specific corpus characteristics informed questions:

- Apple organizes segments geographically, with definitions that differ from country-only interpretations.
- Microsoft's segment presentation changed beginning in fiscal 2025, and workforce geography changes despite repeated total counts.
- NVIDIA's Item 8 refers elsewhere, while its consolidated income statements are physically under Item 15.
- Apple's 2023 Item 1C is not an assertion that cybersecurity risks were absent.
- Tables retain current and historical columns, GAAP and adjusted figures, percentages, monetary scales, and share-count units that can be confused.
- Fiscal-year labels are not calendar-year alignment; cross-company comparisons explicitly use each company's own fiscal year.

Questions avoid embedding the answer, arbitrary identifiers, accession strings, or exact offsets. Named entities, fiscal years, and SEC Item numbers are used where needed to express the task. Wrong-company terminology and false premises are deliberate in the adversarial category. Evidence was selected directly from the source, without consulting any chunking strategy. The ingestion and chunking implementations were not changed.

## Counts and category definitions

Each question has one primary category. Other requirements can overlap: a numerical or comparative question may also require table evidence. The balanced category counts are a design choice, not a model-performance result.

| Category | Count | Intended requirement |
| --- | ---: | --- |
| `direct_factual` | 10 | One localized source passage |
| `section_specific` | 10 | A specified SEC Item and its disclosure |
| `numerical` | 10 | Explicit financial or operational numbers |
| `temporal` | 10 | Correct filing year, fiscal period, or historical column |
| `cross_document` | 10 | Joint facts from at least two specified filings |
| `comparative` | 10 | Comparison across companies or original annual filings |
| `multi_hop` | 10 | Combining multiple source blocks, such as a table and an explanation |
| `table_oriented` | 10 | Values and labels from preserved tables |
| `unanswerable` | 10 | A fact unsupported by this corpus |
| `ambiguous_adversarial` | 10 | Resolve false premises, terminology collisions, or misleading metric/year choices |
| **Total** | **100** | |

The ten adversarial questions are answerable corrections, not under-specified questions with an arbitrarily chosen interpretation. Negative questions belong to the separate unanswerable category.

| Difficulty | Count |
| --- | ---: |
| Easy | 20 |
| Medium | 40 |
| Hard | 40 |

Difficulty is an initial author judgment: direct and explicit numeric facts are easy; section, version, table, and absence checks are medium; cross-document, comparative, multi-hop, and adversarial tasks are hard. These labels have not been calibrated against retrieval performance.

| Support requirement | Count |
| --- | ---: |
| Answerable | 90 |
| Unanswerable | 10 |
| Single-document answerable | 69 |
| Multi-document answerable | 21 |
| No supporting document, unanswerable | 10 |

The ten unanswerable questions are not counted as single-document questions simply because their `multiple_documents_required` value is false. Thirty questions include table evidence. There are 124 evidence entries, representing 76 distinct exact source spans; some evidence is intentionally reused for different failure modes.

### Filing coverage

Counts indicate questions requiring each filing; a multi-document question contributes to each required document.

| Source document | Questions |
| --- | ---: |
| AAPL_000032019323000106 | 10 |
| AAPL_000032019324000123 | 10 |
| AAPL_000032019325000079 | 25 |
| MSFT_000095017024087843 | 12 |
| MSFT_000095017025100235 | 13 |
| MSFT_000119312526323660 | 6 |
| NVDA_000104581024000029 | 7 |
| NVDA_000104581025000023 | 12 |
| NVDA_000104581026000021 | 17 |

Coverage is balanced by primary category, not by company, topic, or year. Apple fiscal 2025 has the most questions and Microsoft fiscal 2026 the fewest. This is a small, correlated benchmark, not a representative sample of enterprise questions.

## Schema and evidence semantics

The top-level object includes the schema version, benchmark ID, construction basis, category targets, evidence policy, offset convention, nine-document corpus manifest, and `questions`.

Each question includes:

- `question_id`: stable `SEC-001` through `SEC-100`; retain IDs when correcting ground truth and version material benchmark changes.
- `question`, `category`, `difficulty`, `answerable`, and `expected_answer`.
- `required_documents`: required document IDs, company/ticker/CIK, form, filing/report dates and years, accession numbers, URLs, and SEC Items.
- `multiple_documents_required`: derived from the number of distinct required source filings.
- `evidence`: exact normalized source text, document/accession/company/ticker/URL, Item and section identity, character offsets, source content block indices, and a table flag.
- `acceptable_answer_variants`: paraphrase and unit guidance, calculation notes, rounding, and distinctions such as actual repurchases versus authorization.
- `query_scope`: target tickers and report years; for answerable items, years identify the source filings, not every historical year mentioned within the question. Negative cases can request an unavailable year or explicitly identify an outside-corpus company.
- `unanswerable_reason` and `absence_audit`: null for positive cases; negatives contain an explicit missing-fact explanation, inspected source document IDs, literal search terms, and inspection notes. An absence audit is not positive answer evidence.
- `review_status` and `review_notes`: source inspection status and known review needs.

Offsets are zero-based Unicode character positions in the parsed document's `text`, with an exclusive end. Evidence may combine consecutive blocks to retain units or table headers, without referring to chunks. All spans lie within their reported SEC Item. The source manifest includes normalized text hashes and original source hashes to detect corpus changes.

Evidence entries are sufficient anchors, not an exhaustive list of every relevant passage. Repeated financial disclosures in MD&A and notes can offer equivalent evidence. Future relevance adjudication should allow equivalent passages in the required filing, while preserving explicit Item restrictions for section-specific questions. Cross-document questions that specify original annual filings require those filings even if a newer comparative table repeats a value. Multi-hop anchors may include adjacent paragraphs; evidence count is not a prescribed minimum number of retrieved chunks.

Keep this directory out of any future document index. Only question text should be submitted as a query; expected answers, source IDs, section metadata, and evidence are ground truth. No train/development/test split is claimed. Related questions share facts—for example, SEC-058 and SEC-099 contrast ordinary comparison with a misleading premise. Before tuning and evaluating later systems, group correlated questions or reserve an independent holdout rather than randomly splitting near-duplicates.

## Unanswerable cases

- SEC-081: model-specific iPhone unit sales, absent from product-category dollar sales.
- SEC-082: the legal identity of NVIDIA's largest direct customer, not established by anonymous concentration disclosures.
- SEC-083: Azure standalone GAAP net income, distinct from Microsoft or Intelligent Cloud results.
- SEC-084–086: actual annual results for periods beyond the respective company's latest filing.
- SEC-087: Samsung consolidated revenue; Samsung is mentioned as a supplier but has no filing in this corpus.
- SEC-088: median employee base salary, not workforce counts or aggregate compensation.
- SEC-089: a CEO compensation table in an incorporated proxy that is not included in the corpus.
- SEC-090: a future realized stock price.

Literal searches were combined with inspection of relevant sections and tables. Mentions of a company, future year, or revenue do not establish the requested fact. A zero search count is not by itself proof of absence. Unanswerability is specific to this frozen corpus, not a claim that the answer is unavailable elsewhere.

## Manual review recommendations

All items were checked against the supplied parsed text, but none has independent human adjudication. Six have explicit additional review flags:

| ID | Review need |
| --- | --- |
| SEC-055 | Workforce percentages derived from approximate employee counts; confirm numerical tolerance. |
| SEC-056 | Qualitative manufacturing comparison; confirm acceptable paraphrase scope. |
| SEC-082 | Confirm that no customer-name mapping is supported; avoid outside industry knowledge. |
| SEC-083 | Confirm absence of Azure standalone GAAP profit across the notes. |
| SEC-088 | Confirm absence of median base salary and distinguish compensation measures. |
| SEC-089 | Confirm that the incorporated proxy compensation table is absent. |

These flags are preserved in JSON and in the validation report. The other negative cases should also receive human review before the dataset is treated as a finalized evaluation standard. In particular, do not turn related company mentions or proxy references into positive evidence.

## Validation and tests

Validation passes for all 100 questions. The script checks ID/text uniqueness, required fields, category targets, labels, date/year and company metadata, parsed/source accession consistency, manifest hashes, evidence existence at exact offsets, Item containment, source block references, table flags, multiple-document requirements, and absence-audit completeness. It rejects a full expected-answer string embedded in a question as a basic leakage guard. That guard cannot detect all semantic answer leakage.

Validation does not prove that a paraphrased answer follows from its evidence, that evidence is exhaustive, that a multi-hop task cannot be answered from another passage, or that a negative fact is absent. Those are semantic review responsibilities; no retrieval scoring has been implemented.

All 33 tests pass: the original 22 ingestion/chunking tests and 11 benchmark tests. New tests cover corrupted evidence, incorrect metadata and offsets, missing fields, duplicate IDs/text, invalid labels, category drift, missing table or multi-document evidence, source hash drift, the leakage guard, CLI failures, and repeat-run report idempotence.

## Phase 3A file inventory

- `evals/ground_truth/sec_retrieval_benchmark.json`: the static benchmark and corpus provenance.
- `evals/ground_truth/validation_report.json`: machine-readable structural validation results.
- `evals/ground_truth/README.md`: this construction and usage guide.
- `scripts/validate_retrieval_benchmark.py`: standalone standard-library validator and CLI.
- `tests/test_retrieval_benchmark.py`: validator and dataset tests.
- `README.md`: Phase 3A usage and links.

No ingestion/chunking architecture or outputs were changed. No dependencies, embeddings, indexes, retrieval algorithms, reranking, RAG, generation pipeline, agents, or evaluation scores were added. Nothing was committed to Git.
