# Historical Phase 5 normalization checkpoint — superseded

> This document preserves the initial blocked diagnosis before raw SEC Company Facts responses were retained. Its “unknown” fields and zero-fact cache describe that earlier checkpoint only. The approved redownload, corrected normalization, accepted coverage, and financial-tool validation are documented in the [financial rebuild report](phase5_financial_rebuild.md) and [final Phase 5 summary](phase5_final_summary.md).

The original three SEC Company Facts responses were not saved. The three existing files are normalized outputs, not raw SEC Company Facts JSON. This prevents the requested raw-data diagnosis and reconstruction. No corruption has been proven and no redownload was performed.

The prior statement that ambiguity caused the empty caches was not established from raw data. It was a hypothesis based on the selector code. It must not be treated as an observed rejection reason for any company or metric.

## Available files

| Company | File | Bytes | Top-level keys |
| --- | --- | ---: | --- |
| AAPL | `data/processed/sec_company_facts/AAPL.json` | 357 | company, metrics, source_url |
| MSFT | `data/processed/sec_company_facts/MSFT.json` | 368 | company, metrics, source_url |
| NVDA | `data/processed/sec_company_facts/NVDA.json` | 365 | company, metrics, source_url |

Each is valid JSON with six empty metric objects. None contains a `facts` object, concept definitions, unit arrays, or source fact rows. Repository searches including ignored files found no retained Company Facts JSON payload. The original downloader used an ordinary requests session without a response cache. It held the decoded response in memory, normalized it, and wrote only `company`, `source_url`, and `metrics`. Successful downloads therefore did not preserve the evidence required for diagnosis.

The nine existing filing HTML documents are different source artifacts; they were not substituted for the missing Company Facts responses.

## Per-company, per-metric inventory

The machine-readable [diagnosis](../evals/generation/phase5/normalization_diagnosis.json) records all requested fields individually for all 18 company/metric combinations. Raw fields are null (unknown), not zero or evidence of absence.

| Metric | Configured concept candidates | AAPL accepted | MSFT accepted | NVDA accepted |
| --- | --- | ---: | ---: | ---: |
| revenue | RevenueFromContractWithCustomerExcludingAssessedTax; SalesRevenueNet | 0 | 0 | 0 |
| net income | ProfitLoss | 0 | 0 | 0 |
| operating income | OperatingIncomeLoss | 0 | 0 | 0 |
| total assets | Assets | 0 | 0 | 0 |
| total liabilities | Liabilities | 0 | 0 | 0 |
| cash and cash equivalents | CashAndCashEquivalentsAtCarryingValue | 0 | 0 | 0 |

For **each company and each metric**: which candidates existed, raw fact counts, units, forms, `fy` values, `fp` values, filing dates, period ends, accession presence, and the actual rejection stage are **unknown because source rows were discarded**. No concept mapping change is justified by these files. These are existing counts; a rebuild was not possible.

## Actual implementation rules, not observed raw-data outcomes

1. **Concept mapping:** read `payload.facts.us-gaap` and visit only the configured concept names. Missing keys previously defaulted silently to empty objects.
2. **Unit filtering:** none. Iterate every unit key. Units are separate grouping keys; there is no USD-only check.
3. **Form filtering:** accept exactly `10-K`; reject all other forms, including `10-K/A`.
4. **Fiscal-year filtering:** accept `isinstance(fy, int)`. This also accepts Python booleans; no range or fiscal-period correspondence is checked.
5. **Fiscal-period filtering:** accept exactly `FY`. Form, fiscal-period, and fiscal-year checks share one condition and discard rows without recording the failed predicate.
6. **Grouping:** group by concept priority, unit, and `fy`. Period start/end and accession are not group keys.
7. **Duplicate/amendment resolution:** sort descending by filing date, accession, and period end; keep all rows with the latest filing date. This is not explicit amendment resolution; amendments were already excluded by form.
8. **Ambiguity rejection:** reject the group when latest-date rows have more than one distinct `(value, unit, concept)` tuple. Different periods can therefore be compared as though they were competing values. Conversely equal values from different periods collapse into one tuple.
9. **Other selection:** skip a group if that fiscal year was already filled by an earlier sorted concept/unit group. No explicit duration, accession-presence, CIK identity, or period validation exists here.

These are code findings. Without raw data, none establishes which branch caused the actual 18 empty results. No selection rule was relaxed or changed to force acceptance.

## Apple fiscal 2025 revenue trace

The original response's `facts.us-gaap` and both configured revenue concept arrays are unavailable. Consequently it is impossible to trace source rows through form, `fy`, `fp`, date selection, and ambiguity rejection or report an original rejection count.

The observable downstream trace is exact:

1. Saved AAPL cache contains `metrics.revenue = {}`.
2. `LocalFinancialData.from_cache_dir` finds no revenue year rows to flatten.
3. `lookup('AAPL', 2025, 'revenue')` obtains an empty list and returns `None` because its length is not one.
4. The financial tool returns `status=unavailable`, `available=false`, reason `No unambiguous local SEC fact`, and empty evidence.

The generic tool reason does **not** prove original SEC ambiguity. There is no resolved concept, value, unit, filing date, accession, or fact-level provenance to report. The cache preserves only company identity and endpoint URL.

Feeding these normalized outputs back to the old normalizer would also silently yield no facts at its initial `payload.get('facts', {})` lookup. That would diagnose an incorrect input shape, not reconstruct the original download. A new guard now rejects that misuse explicitly.

## Confirmed bug fixed

The downloader's loss of the raw response is a confirmed implementation defect. It now saves the complete decoded JSON payload before normalization under `raw/<ticker>-<content-sha256>.json` inside the cache directory. Content-addressed filenames retain different responses, including unsupported concepts and rows normalization rejects. This nested location is excluded from the normalized loader's top-level JSON glob. Preservation is of decoded JSON, not original HTTP response bytes or headers.

The normalizer now requires an actual top-level `facts` object, preventing a normalized cache or malformed top-level payload from silently masquerading as raw data. No financial mapping or row-selection semantics changed. This fix prevents future loss but cannot recover already-discarded data. It was tested with synthetic fixtures only; it made no network calls and did not rebuild or overwrite the existing caches.

Regression tests demonstrate that the raw payload survives even if normalization raises, repeated identical payloads retain the same file, nested raw files do not pollute financial loading, and normalized-only input is rejected.

## Validation and stopping point

- Full offline suite: **87 tests passed**.
- Apple FY2025 revenue explicitly tested through the actual financial tool: **unavailable**, empty evidence.
- All three existing normalized caches remain byte-for-byte unchanged.
- All **154** files in the prior protected artifact audit match their saved hashes; the generation protected manifest also passes.
- All **186** existing files captured for this diagnostic session under data, evaluation, and configuration artifact paths remain unchanged.
- Frozen benchmark SHA-256: `74a2e70d531e389a47730e8c537329ec65cfae5134abec3739a9297feba47e86`.
- No SEC/network requests, Ollama calls, paid calls, model downloads, generation reruns, Phase 6 work, or commits.

Phase 5 remains unaccepted. Completing the requested raw-data diagnosis requires recovering the original responses from an external retained copy, if one exists. Missing retention is not proof of corruption and was not used to justify another download. No demonstration rerun is warranted by this retention-only fix.
