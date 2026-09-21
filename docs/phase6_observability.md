# Phase 6: end-to-end evaluation and observability

Phase 6 is complete. Partial work existed when the session resumed: the observability modules and schema, runtime wrapper, historical adapters, aggregation CLI, 24 tests, and 24 derived historical traces. That implementation was preserved and reviewed, then completed with input-validation hardening, additional regression coverage, full offline verification, and this report. Phases 1–5 were not restarted.

## Files created or completed

| File | Purpose |
|---|---|
| `src/observability/__init__.py` | Package entry |
| `src/observability/trace.py` | Unified trace construction, privacy controls, validation, serialization, and failure classification |
| `src/observability/schema.json` | Machine-readable JSON Schema v6.1 |
| `src/observability/runner.py` | Instrumented execution using existing routing, tools, evidence adapter, prompt builder, provider interface, and validators |
| `src/observability/aggregate.py` | Deterministic aggregation with explicit known/unavailable counts |
| `src/observability/historical.py` | Read-only Phase 4B and Phase 5 adapters |
| `scripts/run_phase6_observability.py` | Offline import/aggregation, report generation, and artifact verification |
| `tests/test_observability.py` | 26 offline tests |
| `evals/observability/phase6/traces/*.json` | 24 unified historical traces |
| `evals/observability/phase6/trace_manifest.json` | Authoritative list of selected trace IDs |
| `evals/observability/phase6/aggregate.json` | Aggregate metrics overall and by historical source |
| `evals/observability/phase6/report.md` | Human-readable historical evaluation |
| `evals/observability/phase6/protected_before.json` | Original 196-file Phase 1–5 preservation snapshot |
| `evals/observability/phase6/protected_audit.json` | Final hash verification |
| `evals/observability/phase6/completion.json` | Completion/test/privacy verification record |
| `docs/phase6_observability.md` | This implementation and completion report |

All implementation changes are confined to new Phase 6 files. Existing generation, retrieval, routing, financial tools, configurations, and Phase 1–5 experimental results are unchanged. No dependencies were added.

## Unified trace schema

The [JSON Schema](../src/observability/schema.json) describes version `6.1`. Runtime traces receive a UUID and UTC timestamp. Historical trace IDs are deterministic from schema version and source identity; original event timestamps remain null because they were not recorded. Fixed inputs serialize deterministically with sorted keys and strict finite JSON numbers. The runtime validator checks the top-level version/fields, safe IDs, timestamps, taxonomy, token counts, and JSON serialization; the published schema also documents nested required fields.

| Section | Recorded information |
|---|---|
| `trace_id`, `timestamp`, `source` | Execution identity, timestamp if known, original trace path/hash and source kind |
| `query` | Query ID; privacy-controlled query text and explicit logging policy |
| `routing` | Decision, reason, selected tools, correctness when labeled, routing elapsed time when measured |
| `tools` | Per-tool name/status, safe original error, elapsed time, evidence provenance |
| `retrieval` | Mode/top-k, retrieved IDs and SEC provenance, elapsed time and timing source, evidence sufficiency and its basis |
| `generation` | Model/provider and allowlisted settings, generation status/elapsed time, input/output/total tokens |
| `validation` | JSON-schema validity, full output-contract validity, citation validity, error categories/details, validation time |
| `abstention` | Observed flag, expected label when available, label agreement |
| `failure_attribution` | One primary category plus all applicable categories |
| `result` | Unified final orchestration status, validation status, evidence sufficiency, optional reviewed claim support, validated citations; answer text withheld |
| `latency` | End-to-end, original recorded elapsed time and scope, orchestration and total tool times |
| `lower_level` | Original orchestration/generation statuses, safe original errors, attempts, original evaluation classifications and available measurements |

The runtime wrapper measures routing and the underlying retriever separately while reusing the existing orchestrator and tool factories. Existing tool timers remain authoritative for per-tool latency. It uses the unchanged evidence adapter, grounded prompt, provider interface, and citation/output validators. Document top-k excludes the independent structured fact, preserving five document chunks plus one financial fact for combined calls. It does not automatically retry providers. Unsupported queries return the existing canonical abstention without needing a provider. Runtime end-to-end timing runs from query entry to validated trace assembly, excluding the disk write.

Only offline fixtures exercised this runtime wrapper in Phase 6. No real provider was invoked.

## Failure taxonomy

The exact machine categories are:

`success`, `expected_abstention`, `unsupported_query`, `retrieval_failure`, `tool_failure`, `routing_failure`, `generation_failure`, `citation_failure`, `invalid_output`, `partial_evidence`.

All applicable categories are retained. Primary precedence is routing failure, tool failure, retrieval failure, partial evidence, generation failure, citation failure, invalid output, unsupported query, expected abstention, success. A valid abstention after inadequate document retrieval can therefore retain both retrieval_failure and expected_abstention. The combined Phase 5 run retains partial_evidence, generation_failure, citation_failure, and invalid_output.

`success` means no failure is established by the available operational checks; it does not certify semantic correctness. Original Phase 4B heuristic classifications remain under `lower_level.legacy_evaluation` rather than being silently treated as measured semantic truth. Original status/error codes are retained; recognized validator messages are preserved verbatim, while arbitrary exception text is withheld for privacy. The source experiments remain intact for provenance.

## Aggregation

Aggregation deduplicates identical trace IDs, rejects conflicting duplicates, and is independent of input order. It reports:

- Query count; routing and invoked-tool success rates.
- Retrieval evidence sufficiency with known denominators and separate label/matcher bases.
- JSON-schema validity and full output-contract validity separately.
- Abstention rate, expected-abstention flag accuracy on positive labels, and abstention-label agreement on all available labels.
- Citation validation, exclusive primary failure counts, and overlapping category counts.
- Mean/median/p95 end-to-end latency, mean/median/p95 retrieval and generation latency, and original elapsed times grouped by timing scope.
- Token sums and averages, both over known observations and over the complete selection when all observations are available.

Percentiles use nearest rank, `ceil(0.95 * n)`. Missing values are null, never zero-filled. Zero tokens are recorded only when a runtime generation is explicitly skipped. Missing token totals can be computed from known input plus output counts; inconsistent reported totals remain unavailable. A provider failure with no usage telemetry does not imply zero tokens. The current saved experiments use one generation attempt per selected execution. For multiple recorded attempts, usage is summed only when each attempt supplies the relevant counts; otherwise the corresponding total remains unavailable.

## Historical results

See the [human-readable historical report](../evals/observability/phase6/report.md), [aggregate JSON](../evals/observability/phase6/aggregate.json), and [trace manifest](../evals/observability/phase6/trace_manifest.json).

The selection contains 20 Phase 4B executions and the four final Phase 5 executions. Phase 4B source traces are matched uniquely to the saved evaluation by question ID, output, status, and latency. Phase 5 uses the saved final-summary paths and verifies their SHA-256 values, preserving its two original and two rerun results. Superseded runs are excluded.

| Metric | Historical result |
|---|---|
| Queries | 24 |
| Routing correctness | 4/4 labeled Phase 5 queries; unavailable for 20 Phase 4B queries |
| Tool success | 4/4 recorded tool invocations; no Phase 4B tool telemetry |
| JSON-schema validity | 24/24 |
| Full output-contract validity | 21/24 (87.5%) |
| Citation-contract validity | 21/24 (87.5%); includes valid empty abstention citations |
| Abstention rate | 12/24 (50%) |
| Expected-abstention flag accuracy | 4/5 labeled positive cases (80%) |
| Evidence sufficiency | Phase 4B required-evidence coverage 7/18; Phase 5 reviewed document sufficiency 0/2 |
| Input/output/total tokens | 100,656 / 1,730 / 102,386 |
| Average total tokens | 4,266.08 per execution |
| Generation latency | Mean 15.401709 s; median 15.259440 s, 24 samples |
| Retrieval latency | Mean 0.002813 s; median 0.001686 s, 20 Phase 4B samples |
| End-to-end latency | Mean/median 9.332703 s; p95 15.236229 s, only two measured Phase 5 samples |

The remaining 22 end-to-end times and all original timestamps are unavailable. Historical Phase 5 retrieval timing covered only an adapter returning already-prepared evidence, not real retrieval. It is preserved as a lower-level adapter duration, with actual retrieval latency null. Document-tool time remains separately recorded. Historical routing and validation-stage durations are also unavailable.

Phase 4B evidence coverage reuses the existing overlap matcher and requires every annotated evidence ID, rather than merely any matching evidence. It remains a benchmark-coverage proxy: alternative valid evidence may exist. Phase 5 uses the accepted prior review. These two bases are not claimed to be equivalent measures of semantic sufficiency. Label scopes and availability are explicit in JSON and the report.

## Privacy

The logging default withholds unreviewed free text: queries, raw model answers, prompts, evidence text, arbitrary exceptions, and personal fields. Query IDs and allowlisted SEC filing/fact identifiers remain available for investigation. It logs neither environment dictionaries nor credential-setting names/values. The known configured secret and SEC User-Agent are used only in memory for redaction. Email, phone, SSN, and API-token patterns are additionally removed; SEC URL credentials and query strings are excluded.

An explicit `Privacy(reviewed_queries={original: reviewed_public_text})` allowlist can retain a reviewed public query. Names and addresses must be excluded during that review; pattern matching alone cannot guarantee their recognition. No historical query text was automatically granted that exception. The tests exercise default name/address suppression and secret/email/phone/SSN redaction.

## Validation and preservation

The complete offline suite passes: **116 tests**, including **26 Phase 6 tests**. Coverage includes financial/document/combined flows, unsupported and expected abstention, routing/retrieval/tool/generation/citation/invalid-output failures, overlapping partial evidence, context provenance tampering, stage timing, token sums/missingness, privacy, deterministic serialization, historical import, CLI idempotence, saved-trace reaggregation, schema validation, unsafe identifiers, and malformed token counts.

All **196 snapshotted Phase 1–5 artifacts** remain byte-for-byte unchanged. The original protected manifest also passes. Frozen benchmark SHA-256:

`74a2e70d531e389a47730e8c537329ec65cfae5134abec3739a9297feba47e86`

No network, Ollama, paid API, model download, SEC download, prior-generation rerun, Phase 7 work, or Git commit was performed.

## Usage

```bash
.venv/bin/python scripts/run_phase6_observability.py
.venv/bin/python scripts/run_phase6_observability.py \
  --trace-dir evals/observability/phase6/traces \
  --output evals/observability/phase6/reaggregated
.venv/bin/python -m unittest discover -s tests
```

The CLI only ingests saved data. Runtime instrumentation is available through `src.observability.runner.run_query` with explicitly supplied retriever, financial data, provider, configuration, and optional evaluation labels. It returns a privacy-filtered trace; `save_trace` persists it. Disk writes are separate from measured query processing.

Remaining limits are historical telemetry gaps, reviewed-label dependence for semantic evidence sufficiency, conservative free-text logging, no automatic semantic entailment evaluator. No external observability service is required.

### Later portfolio hygiene note

Phase 8 replaced the absolute machine-local Ollama binary path in `evals/generation/phase4a_ollama/installation.json` with a generic placeholder. This file is installation metadata, not a generated model result. The Phase 5/6 protected-audit expected hashes were updated for this single privacy cleanup; benchmark data, filing data, rankings, generation outputs, and other protected files were not changed.
