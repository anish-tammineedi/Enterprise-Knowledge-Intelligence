# Phase 5 retained SEC facts: diagnosis and offline rebuild

This report records the SEC Company Facts diagnosis and deterministic cache rebuild. The subsequent minimal Phase 5 demonstrations were validated; see the [final Phase 5 summary](phase5_final_summary.md). Exactly the three approved Company Facts endpoints were requested once each using the configured SEC_USER_AGENT, 30-second timeout, and at least 0.25 seconds between requests. No retries or further downloads were initiated. Raw decoded JSON responses are retained in content-addressed files under `data/processed/sec_company_facts/raw/`; normalized caches remain separate top-level files.

## Confirmed causes and mapping corrections

The old normalizer treated `fy` as the period belonging to every row. In these responses, one annual filing supplies multiple comparative periods carrying the same filing fiscal-year label. It selected all rows on the newest filing date and rejected their different values as ambiguity without first separating periods. This affects both duration and instant metrics. Apple FY2025 revenue demonstrates the bug directly below.

`ProfitLoss` is absent in all three raw us-gaap dictionaries. Each contains `NetIncomeLoss`, labeled “Net Income (Loss) Attributable to Parent,” with the description identifying profit or loss net of income taxes attributable to the parent. The net-income mapping is now explicitly that concept; it is not assumed interchangeable with a broader consolidated profit concept.

Revenue retains the original priority order `RevenueFromContractWithCustomerExcludingAssessedTax`, then `SalesRevenueNet`, and adds `Revenues` last. The retained `Revenues` concept is labeled “Revenues” and described as revenue recognized from goods sold, services rendered, and other earning activities. It contains NVIDIA’s current annual revenue rows, while the contract-revenue concept has no NVIDIA FY2025 annual rows. It also supplies older Apple/Microsoft annual rows. No mappings for the other four metrics changed. No benchmark answers were consulted.

## Deterministic selection and validation

1. Validate the raw top-level facts/us-gaap structure, concept unit arrays, and CIK against the configured company before normalization.
2. Require USD, finite numeric values, 10-K or 10-K/A, integer fiscal-year labels (not booleans), FY, a nonempty accession, valid ISO dates, and period end no later than filing date.
3. For each annual accession and fiscal-year label, use the latest instant Assets end date as the current fiscal-period anchor. Keep only metric rows ending on that date. This avoids assuming that fiscal years coincide with calendar years; NVIDIA FY2025 ends in January 2025.
4. Require revenue, net income, and operating income to cover 350–380 inclusive days, supporting ordinary calendar and 52/53-week fiscal years. Short transition periods, quarters, and missing durations remain unavailable. Require balance-sheet metrics to be instant facts with no start.
5. Use the newest anchored annual filing date for each fiscal year, including amendments. Do not silently use older facts when the latest anchored filing lacks the metric. If newest-date anchors disagree on period, leave the year unavailable.
6. Apply configured concept priority to eligible current-period facts. Collapse only identical start/end/value/unit/concept tuples; conflicting values or durations remain unavailable. Deterministically choose accession/index for identical duplicate records. No fallback to a lower-priority concept after ambiguity.
7. Preserve company, CIK, fiscal year, concept, unit, dates, form, accession, endpoint, raw-file SHA-256, and exact JSON pointer in each accepted fact.

The Assets anchor is a conservative rule for this supported corpus, not a universal SEC filing-calendar implementation. Missing anchors and short transition years remain unavailable. There were no unresolved same-period value conflicts among the accepted-year groups in these three snapshots.

## Coverage and candidates

R = RevenueFromContractWithCustomerExcludingAssessedTax; S = SalesRevenueNet; V = Revenues; N = NetIncomeLoss; O = OperatingIncomeLoss; A = Assets; L = Liabilities; C = CashAndCashEquivalentsAtCarryingValue.

Candidate counts below mean mapped raw rows passing annual form/FY/year/date/accession checks before current-period/duration selection. “Raw” counts include quarterly and comparative rows. The machine-readable report additionally provides per-concept counts, forms, raw fiscal-year labels, filter counts, and accepted-year lists. Selected concepts are the union across accepted years; each normalized fact identifies its exact concept.

| Company | Metric | Selected concepts | Units present | Annual forms present | Raw | Annual candidates | Accepted | Accepted fiscal years |
|---|---|---|---|---|---:|---:|---:|---|
| AAPL | revenue | R, V, S | USD | 10-K, 10-K/A | 338 | 142 | 17 | 2009–2025 |
| AAPL | net income | N | USD | 10-K, 10-K/A | 338 | 142 | 17 | 2009–2025 |
| AAPL | operating income | O | USD | 10-K, 10-K/A | 234 | 54 | 17 | 2009–2025 |
| AAPL | total assets | A | USD | 10-K, 10-K/A | 146 | 38 | 17 | 2009–2025 |
| AAPL | total liabilities | L | USD | 10-K, 10-K/A | 144 | 36 | 17 | 2009–2025 |
| AAPL | cash and cash equivalents | C | USD | 10-K, 10-K/A | 228 | 58 | 17 | 2009–2025 |
| MSFT | revenue | R, V, S | USD | 10-K | 338 | 143 | 17 | 2010–2026 |
| MSFT | net income | N | USD | 10-K | 340 | 143 | 17 | 2010–2026 |
| MSFT | operating income | O | USD | 10-K | 278 | 91 | 17 | 2010–2026 |
| MSFT | total assets | A | USD | 10-K | 142 | 34 | 17 | 2010–2026 |
| MSFT | total liabilities | L | USD | 10-K | 134 | 32 | 16 | 2011–2026 |
| MSFT | cash and cash equivalents | C | USD | 10-K | 266 | 54 | 17 | 2010–2026 |
| NVDA | revenue | R, V | USD | 10-K | 308 | 134 | 16 | 2010–2013, 2015–2026 |
| NVDA | net income | N | USD | 10-K | 314 | 132 | 16 | 2010–2013, 2015–2026 |
| NVDA | operating income | O | USD | 10-K | 225 | 51 | 16 | 2010–2013, 2015–2026 |
| NVDA | total assets | A | USD | 10-K | 138 | 34 | 16 | 2010–2013, 2015–2026 |
| NVDA | total liabilities | L | USD | 10-K | 86 | 22 | 11 | 2016–2026 |
| NVDA | cash and cash equivalents | C | USD | 10-K | 219 | 54 | 16 | 2010–2013, 2015–2026 |

Total: **294 accepted facts** (AAPL 102, MSFT 101, NVDA 91).

MSFT liabilities FY2010 and NVDA liabilities FY2010–2013/FY2015 have no eligible Liabilities fact in the latest anchored annual filing; no liabilities are inferred from other concepts. NVIDIA FY2014 has no FY annual rows in the retained Assets, Revenues, or NetIncomeLoss arrays, so it is not reconstructed from later comparative rows. Years outside the listed accepted ranges also remain unavailable.

## Apple FY2025 revenue end-to-end

The primary configured revenue concept exists, with 117 USD raw rows across fiscal periods. These three annual raw rows all carry fy=2025, fp=FY, form=10-K, filed=2025-10-31 and accession 0000320193-25-000079:

| Start | End | Value (USD) | Outcome |
|---|---|---:|---|
| 2022-09-25 | 2023-09-30 | 383,285,000,000 | Excluded comparative period |
| 2023-10-01 | 2024-09-28 | 391,035,000,000 | Excluded comparative period |
| 2024-09-29 | 2025-09-27 | 416,161,000,000 | Accepted current annual period |

Old behavior: the three values form three distinct value/unit/concept tuples on the same newest filing date, so the entire FY2025 group was rejected. New behavior: the same accession’s Assets instants end on 2024-09-28 and 2025-09-27. The latter anchors the current fiscal year. Only the revenue row ending 2025-09-27 survives; its inclusive duration is 364 days. There is one current annual candidate, no duplicate conflict, and no amendment to resolve for this case.

The normalized fact and direct financial-tool result agree: **416,161,000,000 USD**, concept `RevenueFromContractWithCustomerExcludingAssessedTax`, FY2025, period end 2025-09-27, form 10-K, filed 2025-10-31, accession `0000320193-25-000079`.

Source endpoint: `https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json`. Raw file: `data/processed/sec_company_facts/raw/AAPL-855f2ebb1772459bd63857601193fa380b5eef53341d5cafe59216fe350bd9d5.json`. SHA-256: `855f2ebb1772459bd63857601193fa380b5eef53341d5cafe59216fe350bd9d5`. Exact JSON pointer: `/facts/us-gaap/RevenueFromContractWithCustomerExcludingAssessedTax/units/USD/111`. The raw source row, normalized fact, and tool output are recorded together in the [machine-readable report](../evals/generation/phase5/financial_rebuild_report.json).

## Direct financial-tool checks

| Lookup | Status | Concept | Value | Period end | Filed | Accession |
|---|---|---|---:|---|---|---|
| AAPL FY2025 revenue | success | RevenueFromContractWithCustomerExcludingAssessedTax | 416,161,000,000 USD | 2025-09-27 | 2025-10-31 | 0000320193-25-000079 |
| MSFT FY2025 net_income | success | NetIncomeLoss | 101,832,000,000 USD | 2025-06-30 | 2025-07-30 | 0000950170-25-100235 |
| NVDA FY2025 revenue | success | Revenues | 130,497,000,000 USD | 2025-01-26 | 2025-02-26 | 0001045810-25-000023 |
| AAPL FY1900 revenue | unavailable | — | — | — | — | — |

The unavailable case returns available=false and empty evidence.

## Validation

- Complete offline suite: **90 tests passed**. Regression fixtures cover comparative annual rows plus quarters, exact duplicates, conflicting values/durations, amendment selection, missing anchors, wrong CIK, invalid shapes, unsupported units, and boolean years.
- All three raw-file content hashes verify. Every accepted fact’s value and accession were checked against its exact retained raw-array index.
- `scripts/rebuild_sec_company_facts.py --check` recomputes from raw files and matches all three normalized caches byte-for-byte; it makes no network calls.
- The original protected manifest passes, and all **154 Phase 1–4B artifact hashes** match the prior audit.
- Benchmark SHA-256 remains `74a2e70d531e389a47730e8c537329ec65cfae5134abec3739a9297feba47e86`.
- No Ollama calls, demonstration reruns, Phase 6 work, paid API calls, model downloads, benchmark changes, or Git commits.

Reproduction: `.venv/bin/python scripts/rebuild_sec_company_facts.py` rebuilds offline; append `--check` to verify without writes. The script refuses multiple retained raw versions per company instead of silently choosing a snapshot.

Stopped after financial normalization and validation. The earlier Phase 5 demonstration outcomes remain historical and unchanged.
