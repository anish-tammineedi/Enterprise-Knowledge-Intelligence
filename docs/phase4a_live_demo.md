# Phase 4A local live demonstration

Phase 4A is complete as infrastructure plus a four-question live demonstration. Three responses are validated abstentions; one is rejected. There are no accepted substantive answers in this sample. This does not establish answer quality or production readiness.

## Configuration

- Ollama 0.34.1; local Apple M4/Metal execution.
- Model: `qwen3:4b-instruct-2507-q4_K_M`.
- Exact digest: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
- SEC section-aware BM25, top 5; temperature 0, seed 0, thinking disabled, context window 16,384, maximum output 1,000 tokens, timeout 600 seconds, no retries.
- Full configuration, original trace references and context/provenance mappings: [machine-readable report](../evals/generation/phase4a_ollama/live_demo_report.json).

## Saved results

| Question | Category | Status | Latency (s) | Input / output tokens |
|---|---|---|---:|---:|
| SEC-001 | direct_factual | success | 14.96 | 4138 / 23 |
| SEC-021 | numerical | success | 18.04 | 5733 / 23 |
| SEC-061 | multi_hop | invalid_output | 17.78 | 5071 / 58 |
| SEC-081 | unanswerable | success | 16.54 | 5017 / 23 |

All four used BM25 top 5 and question-scoped context identifiers `C001`–`C005`. Exact chunk IDs, text and provenance are preserved in the JSON report and original traces. Latency includes retrieval, generation and validation.

### SEC-001 — direct_factual

According to Apple’s fiscal 2025 business description, what does its cloud service do for customers across devices?

Original model output:

```json
{"abstained":true,"answer":"Insufficient evidence in the supplied SEC context.","citations":[]}
```

Retrieval insufficiency: no Apple passage in the top five. The model appropriately abstained on an answerable corpus question.

Validation: passed. Accepted citations: []. Accepted abstention state: true.

[Original trace](../evals/generation/phase4a_ollama/traces/45f194ee5d535e31ca93a32b8d699eaed538d3069347bfaba85608b19abd7166.json)

### SEC-021 — numerical

Approximately how many full-time-equivalent employees did Apple report at September 30, 2023?

Original model output:

```json
{"abstained":true,"answer":"Insufficient evidence in the supplied SEC context.","citations":[]}
```

Retrieval insufficiency: the retrieved Apple passages do not supply the requested employee count. The model appropriately abstained.

Validation: passed. Accepted citations: []. Accepted abstention state: true.

[Original trace](../evals/generation/phase4a_ollama/traces/3f271b986dac9a4bcb2738d471ae3e653ca6e8446f8cdd2d6c5e96f310cb9485.json)

### SEC-061 — multi_hop

In Apple’s fiscal 2025 filing, which geographic segment had the highest reported percentage sales growth and what products or services drove that segment’s increase?

Original model output:

```json
{"abstained":false,"answer":"In Apple’s fiscal 2025 filing, the Americas segment had the highest reported percentage sales growth at 7%. This growth was primarily driven by higher net sales of iPhone and Services.","citations":["C002"]}
```

Generation and citation-format failure. The answer omits inline [C002] despite listing C002. Additionally, C002 explicitly shows Japan at 15%, driven by iPhone, Services and iPad; the raw answer incorrectly selects Americas at 7%. Evidence was available in context. The validator correctly rejected the response; it does not establish semantic correctness.

Validation: Inline citations and citation list differ. Accepted citations: []. Accepted abstention state: null.

[Original trace](../evals/generation/phase4a_ollama/traces/9353289930f4d82f4bc3b8cb79df961a851a13c0efd7e06aeee20f981c474379.json)

### SEC-081 — unanswerable

How many iPhone 17 units did Apple sell during fiscal 2025?

Original model output:

```json
{"abstained":true,"answer":"Insufficient evidence in the supplied SEC context.","citations":[]}
```

Expected abstention for a corpus-unsupported iPhone unit-sales question.

Validation: passed. Accepted citations: []. Accepted abstention state: true.

[Original trace](../evals/generation/phase4a_ollama/traces/86ebd851c5b9be3db7c39973151a11b76b47f56dcf5635b7a65eb3ccd038f070.json)

## Verification and interpretation

- All 69 tests passed in 8.302 seconds; the full suite ran once during this continuation.
- Verified all four trace hashes, prompt/configuration hashes, saved configuration, reconstructed retrieval contexts and prompts, and output validation replay. SEC-061 reproduces its original rejection.
- Verified the installed binary and model manifest against the installation record, plus all 125 protected artifact hashes.
- No additional generation, paid API calls, installations, downloads, full benchmark run or commits. Existing traces and protected artifacts were preserved.
- Aggregate recorded latency: 67.31 seconds across four original calls (16.83 seconds/query); 19,959 input and 127 output tokens, 20,086 total.

## Findings for Phase 4B

- Separate retrieval insufficiency, incorrect generation, citation-format failure and expected abstention in evaluation.
- Measure abstention on answerable questions separately from appropriate abstention on unsupported questions.
- Assess numerical/table comparisons and claim support: SEC-061 had the correct evidence but selected the wrong segment.
- Citation existence and schema checks do not establish factual correctness. Track citation formatting and semantic support independently.
- Compare retrieval modes/context sizes in declared experiments without changing frozen evidence or repairing past outputs.

Phase 4B has not begun. No live demonstration work remains blocked. The rejected result remains an observed failure, not a passing answer.

## Files created in this continuation

- `docs/phase4a_live_demo.md`: this report.
- `evals/generation/phase4a_ollama/live_demo_report.json`: saved outputs, configuration, provenance/context mappings, trace hashes and audit findings.
