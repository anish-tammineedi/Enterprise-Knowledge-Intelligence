# Phase 5 deterministic agent and financial data

Phase 5 is complete with documented failures. The accepted final results are in the [Phase 5 final summary](phase5_final_summary.md); detailed SEC Company Facts normalization and provenance are in the [financial rebuild report](phase5_financial_rebuild.md). This page summarizes the system design.

The router selects document retrieval for SEC narrative questions, `financial_data` for supported company/period/metric requests, both tools for combined questions, and abstention for unsupported patterns. Routing is deterministic and runs before generation. The document tool returns original SEC section evidence and provenance. The financial tool reads retained SEC Company Facts JSON normalized into accepted annual facts.

Supported metrics are revenue, net income, operating income, total assets, total liabilities, and cash and cash equivalents. Normalized facts preserve ticker, CIK, concept, unit, fiscal year, period dates, form, filing date, accession, source URL, raw-response hash, and JSON pointer. Missing, ambiguous, or unsupported facts remain unavailable.

The final cache contains 294 accepted facts across AAPL, MSFT, and NVDA. Apple FY2025 revenue resolves to 416,161,000,000 USD from `RevenueFromContractWithCustomerExcludingAssessedTax`. The financial-only demonstration succeeded. The combined demonstration retrieved insufficient Apple narrative evidence and produced an invalid output; it remains recorded as a failure without a retrieval or generation retry. See the final summary for routing, tool, citation, and abstention details.
