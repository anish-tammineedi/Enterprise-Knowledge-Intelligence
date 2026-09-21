# Phase 5 final validation

**Phase 5 is complete with documented failures.** Implementation and the requested minimal validation are complete. This does not mean all four questions were answered successfully: financial-only now passes, while combined remains a partial-evidence failure and also fails the generation contract.

Exactly two new local Ollama generations were made, once each, with no retries. The original document-only and unsupported demonstrations are preserved by path and SHA-256. Retrieval remains SEC-section BM25 top five; the prompt, model/digest, temperature, context size, output limit, and seed are unchanged. No SEC download or paid call occurred.

The revalidation runner invokes the existing evidence adapter, prompt builder, provider, and validators directly. Its document limit stays five; the independent financial fact is a sixth context in the combined case. The older document-generation wrapper capped total contexts at five, so it cannot represent this combination without miscounting a financial fact as a document chunk. No retrieval or generation settings were changed.

## Results across all four demonstrations

| Demonstration | Execution | Routing | Tool execution | Evidence sufficiency | Generation | Citation/provenance | Abstention |
|---|---|---|---|---|---|---|---|
| Document-only | Preserved original | Correct | Retrieval executed | Insufficient: Apple chunk says Not applicable; four other-company chunks | Correct abstention | Returned provenance retained; no answer citations | Correct |
| Financial-only | One new generation | Correct | Financial lookup succeeds | Sufficient | Correct answer | C001 validates and matches raw financial provenance | Correctly answered |
| Combined | One new generation | Correct | Both tools execute successfully | Financial sufficient; document insufficient | Invalid partial answer | Raw C006 identifies the fact, but no inline citation; rejected | Failed to abstain |
| Unsupported | Preserved original | Correct, no tools | Correctly invokes no tools | Unsupported source pattern | Correct abstention | No citations required | Correct |

Routing: **4/4 correct**. Tool execution: **4/4 correct for selected routes**, including no invocation for unsupported. Generation/abstention contract: **3/4 correct**. Only the financial-only question receives a substantive validated answer. A successful retrieval call does not establish evidence relevance.

## Two new demonstrations

### P5-FIN-001

What was Apple’s revenue in fiscal 2025?

- Routing/tools: financial_data.
- Routing reason: standardized financial metric and fiscal year detected.
- Final status: `success`.
- JSON/schema validity: yes. Full output-contract validity: True.
- Every factual claim supported semantically: True. Single claim (AAPL FY2025 revenue 416161000000 USD) exactly matches returned financial fact and C001.
- Generation correctness: True. Correctly answered
- Raw citation list: `["C001"]`; validated citations: `["C001"]`.
- Latency: 3.429177s preparation + generation; 3.428811s generation/provider; 0.000283s orchestration (included in preparation).
- Tokens: input_tokens=468, output_tokens=53, total_tokens=521.

Financial fact returned:

```json
{
  "accession_number": "0000320193-25-000079",
  "cik": "0000320193",
  "company": "Apple Inc.",
  "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
  "concept_mapping": [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "Revenues"
  ],
  "duplicate_rows_resolved": 0,
  "end": "2025-09-27",
  "filing_date": "2025-10-31",
  "fiscal_year": 2025,
  "form": "10-K",
  "metric": "revenue",
  "period_anchor": "Assets: latest instant end in the same annual accession",
  "raw_fact_pointer": "/facts/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax/units/USD/111",
  "raw_file": "data/processed/sec_company_facts/raw/AAPL-855f2ebb1772459bd63857601193fa380b5eef53341d5cafe59216fe350bd9d5.json",
  "raw_sha256": "855f2ebb1772459bd63857601193fa380b5eef53341d5cafe59216fe350bd9d5",
  "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
  "start": "2024-09-29",
  "ticker": "AAPL",
  "unit": "USD",
  "value": 416161000000
}
```

Document evidence:

None; document retrieval was not invoked.

Final raw model output (unchanged):

```json
{"abstained":false,"answer":"Apple’s revenue in fiscal 2025 was $416,161,000,000 USD [C001].","citations":["C001"]}
```

Validated final answer:

> Apple’s revenue in fiscal 2025 was $416,161,000,000 USD [C001].

Trace: [P5-FIN-001](../evals/generation/phase5/financial_revalidation/P5-FIN-001.json).

### P5-BOTH-001

What was Apple’s revenue in fiscal 2025, and what products or services drove the change?

- Routing/tools: document_retrieval, financial_data.
- Routing reason: financial fact requested with narrative explanation.
- Final status: `partial_evidence_failure_and_invalid_output`.
- JSON/schema validity: yes. Full output-contract validity: False.
- Every factual claim supported semantically: True. Revenue rounded to $416.16 billion is supported by C006. Statement that supplied evidence lacks Apple revenue drivers is consistent with all five document chunks belonging to MSFT/NVDA. No invented product-driver claim, but the question is not fully answered and claims lack valid inline citation.
- Generation correctness: False. Incorrectly returned abstained=false despite missing evidence for part of the question; prompt required canonical full abstention.
- Raw citation list: `["C006"]`; validated citations: `[]`.
- Latency: 15.236229s preparation + generation; 15.235263s generation/provider; 0.000735s orchestration (included in preparation).
- Tokens: input_tokens=4701, output_tokens=54, total_tokens=4755.

Financial fact returned:

```json
{
  "accession_number": "0000320193-25-000079",
  "cik": "0000320193",
  "company": "Apple Inc.",
  "concept": "RevenueFromContractWithCustomerExcludingAssessedTax",
  "concept_mapping": [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "Revenues"
  ],
  "duplicate_rows_resolved": 0,
  "end": "2025-09-27",
  "filing_date": "2025-10-31",
  "fiscal_year": 2025,
  "form": "10-K",
  "metric": "revenue",
  "period_anchor": "Assets: latest instant end in the same annual accession",
  "raw_fact_pointer": "/facts/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax/units/USD/111",
  "raw_file": "data/processed/sec_company_facts/raw/AAPL-855f2ebb1772459bd63857601193fa380b5eef53341d5cafe59216fe350bd9d5.json",
  "raw_sha256": "855f2ebb1772459bd63857601193fa380b5eef53341d5cafe59216fe350bd9d5",
  "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
  "start": "2024-09-29",
  "ticker": "AAPL",
  "unit": "USD",
  "value": 416161000000
}
```

Document evidence:

**Financial evidence succeeded. Document evidence was insufficient:** none of the five chunks is from Apple. They cannot substantiate which Apple products or services drove the FY2025 change. The five returned documents match the original combined run exactly.

| Context | Company | Accession | Item | Chunk ID |
|---|---|---|---|---|
| C001 | MSFT | 0001193125-26-323660 | 7 | `99e61f0fde0104af67a3787c892d95a2ddbf88034ba3374495ef66bb8513d2f6` |
| C002 | NVDA | 0001045810-25-000023 | 7 | `af4c5eb8d020641730d7c4163a4ca37522181890c2b84d6288548d36a1efb05e` |
| C003 | MSFT | 0000950170-25-100235 | 7 | `7b65f5a81e76aefd39ebae2d6f742de26d9ebe1e5cd0a317cc6eb829f9700aba` |
| C004 | NVDA | 0001045810-25-000023 | 7 | `8103f7d0a1881c47ab4f56272f2c03e410c471a26d063d3e11f9d848b570745b` |
| C005 | NVDA | 0001045810-25-000023 | 7 | `d80166250305e5df65e667cd39b05917a7858de6d583491c52dd4160641b1c6f` |

The full returned texts, source URLs, section IDs, offsets, and provenance are retained in the linked trace and final-summary JSON. C006 is the independent Apple financial fact.

Final raw model output (unchanged):

```json
{"abstained":false,"answer":"Apple’s revenue in fiscal 2025 was $416.16 billion. The provided evidence does not specify which products or services drove the change in revenue.","citations":["C006"]}
```

Validated final answer:

**None. Output rejected:** Inline citations and citation list differ. No repaired or substituted answer was generated.

Trace: [P5-BOTH-001](../evals/generation/phase5/financial_revalidation/P5-BOTH-001.json).

## Preserved demonstrations

- P5-DOC-001: [evals/generation/phase5/traces/8ad25456fdb542e7be949971d5b50dbb41ac707b930b0a3c0373ee1625972e1e.json](../evals/generation/phase5/traces/8ad25456fdb542e7be949971d5b50dbb41ac707b930b0a3c0373ee1625972e1e.json). Original answer: “Insufficient evidence in the supplied SEC context.” Original latency 11.200584416015772s; token usage {"input_tokens": 3309, "output_tokens": 23, "total_tokens": 3332}. No regeneration.
- P5-ABSTAIN-001: [evals/generation/phase5/traces/635c0ceefe9461ad4277d1d669ff09fb3b3f5f18fb52cf19beaacedb324cea9b.json](../evals/generation/phase5/traces/635c0ceefe9461ad4277d1d669ff09fb3b3f5f18fb52cf19beaacedb324cea9b.json). Original answer: “Insufficient evidence in the supplied SEC context.” Original latency 0.9100628329906613s; token usage {"input_tokens": 233, "output_tokens": 23, "total_tokens": 256}. No regeneration.

## Financial coverage and validation

Supported metrics: revenue, net income attributable to parent, operating income, total assets, total liabilities, and cash and cash equivalents. **294 accepted structured facts:** AAPL 102, MSFT 101, NVDA 91. Details and historical gaps remain in the [financial rebuild report](phase5_financial_rebuild.md).

| Direct financial-tool check | Result |
|---|---|
| AAPL FY2025 revenue | 416,161,000,000 USD; success |
| MSFT FY2025 net income | 101,832,000,000 USD; success |
| NVDA FY2025 revenue | 130,497,000,000 USD; success |
| AAPL FY1900 revenue | Unavailable, empty evidence |

The direct checks are preserved from the accepted offline rebuild; new financial-only and combined tool executions also both returned the Apple fact successfully.

- Full offline suite after adding the minimal runner: **90 passed**.
- Frozen benchmark SHA-256: `74a2e70d531e389a47730e8c537329ec65cfae5134abec3739a9297feba47e86`; unchanged.
- All **154 Phase 1–4B protected artifacts** match their prior hashes; protected manifest verification passes.
- Original four Phase 5 generation traces and live report, generation configuration, raw Company Facts files, and normalized financial caches also remain byte-for-byte unchanged. See [preservation audit](../evals/generation/phase5/financial_revalidation/preservation_audit.json).
- No retrieval/generation tuning, retries, paid API calls, model downloads, SEC redownloads, Phase 6 work, or Git commits.

## Remaining limitations

- BM25 retrieves wrong-company narrative evidence for these questions.
- Combined model output did not obey full-abstention or inline-citation rules.
- Structured financial coverage is limited to pinned metrics, USD, annual periods, and accepted raw snapshots; historical gaps remain.
- Deterministic routing is rule-based, not a general reasoning planner.
- Citation validators check identity/provenance and output contracts; semantic support was separately reviewed for these demonstrations.

Machine-readable results with complete evidence, raw/validated outputs, metrics, and provenance: [final summary](../evals/generation/phase5/final_summary.json).
