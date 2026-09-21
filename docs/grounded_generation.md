# Phase 4A: grounded generation infrastructure

## Status

The provider interface, OpenAI adapter, SEC retrieval integration, deterministic prompts, output/citation validation, abstention handling, traces and tests are implemented. No live API calls, paid usage, generation-model downloads, or full benchmark generation were performed. The four-question live demonstration is intentionally deferred by the user.

The initial configured provider is OpenAI, model `gpt-4.1-mini-2025-04-14` (the dated GPT-4.1 mini snapshot). The adapter follows the official [Responses structured-output format](https://developers.openai.com/api/docs/guides/structured-outputs). The [model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini) describes structured-output support. The adapter is implemented and exercised through mocked HTTP responses; actual account/model availability and live output behavior remain unverified.

No new dependencies were needed. Existing requests and NumPy support HTTP transport and retrieval. Credentials are read from the configured environment variable only when the backend generates; no credential is required to import modules, prepare prompts, retrieve the sample, or run tests.

## Usage

Run all tests:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Offline preparation is the CLI default. These commands retrieve context and save prompts only; they do not instantiate an LLM provider or make API calls:

```bash
.venv/bin/python scripts/run_grounded_generation.py
.venv/bin/python scripts/run_grounded_generation.py --mode hybrid --top-k 10
```

The CLI is deliberately limited to four representative questions, choosing the first question in each requested category: SEC-001 (direct factual), SEC-021 (numerical), SEC-061 (multi-hop), SEC-081 (unanswerable). Selection does not inspect retrieval success or expected answers. There is no full-benchmark CLI option.

After separate authorization for the deferred paid demonstration, the user can configure `OPENAI_API_KEY` in the process environment, then explicitly invoke:

```bash
.venv/bin/python scripts/run_grounded_generation.py --live
```

That command was **not** run. Credentials should not be entered into repository files or chat. The initial four-question live run remains subject to paid-usage approval; retries can issue additional requests within configured limits.

## Configuration

`configs/generation.json` separates:

- `llm`: provider/model, temperature (default zero), maximum output tokens (1,000), request timeout (45 seconds), maximum retries (two), exponential retry delay (one second initially), and credential environment-variable name.
- `retrieval`: BM25 or hybrid, top K, existing dense run and lexical configuration paths. BM25/top-five is the initial context configuration; both top-five and top-ten are tested for both modes.
- `prompt`: explicit version and a character budget. Oversized context is rejected rather than silently truncating chunks. This character cap is not a tokenizer estimate.
- Protected artifact manifest and a new generation-only output directory.

No cross-encoder reranking is the default. A future experimental reranked retriever can implement the same `Retriever.retrieve(question, mode, top_k)` contract and supply ordinary original chunk records without changing prompt construction or the provider interface.

The interface accepts arbitrary `Question(question_id, text)` records. For an unseen question in hybrid mode, the retriever uses the already-installed local dense encoder; missing model files cause an explicit preparation error, not an automatic model download. The four frozen sample queries use their existing cached embeddings. BM25 requires no embedding model.

## Data flow and leakage boundary

1. Project the selected benchmark record to `Question` containing only identifier and question text. Category is used by the sample selector, never by the model. The generation layer does not accept benchmark records, expected answers, required documents, evidence annotations or answerability labels.
2. Retrieve original SEC section-aware chunks with the existing BM25 or dense+BM25 RRF implementation. No gold-based filtering or evidence matching participates in retrieval or generation.
3. Allowlist chunk text/provenance fields into numbered contexts C001, C002, etc. Chunk fields outside that allowlist cannot leak into the prompt.
4. Serialize the question and evidence as canonical JSON, accompanied by deterministic instructions.
5. Call the injected provider with only instructions, serialized question/evidence, response schema and LLM configuration.
6. Validate the returned object and all citation references, then store a trace.

Tests mutate benchmark answers, evidence, required documents, difficulty and answerability into sentinel strings and verify that the public questions and prompts remain unchanged. Public question text can naturally contain numbers or words also occurring in answers; this boundary prevents leakage from annotations rather than removing legitimate question content.

## Prompt and context contract

Every context contains its context ID, chunk ID, document/source-document identifiers, company, ticker, CIK, form, filing/report dates and years, accession, Item/section identifiers and names, source URL, character offsets and exact chunk text. Unsectioned content keeps the original null Item/section fields. Original chunks are not rewritten or re-split.

The prompt requires answers from supplied evidence alone; distinctions between companies, years, units and comparative table columns; abstention when any necessary part of a question is unsupported; and inline citations for factual assertions. It explicitly treats filing text and question text as untrusted data rather than instructions. Neither prompting nor identifier validation guarantees semantic correctness or resistance to every injected instruction; that remains a limitation to investigate in later evaluation.

Canonical JSON key ordering and stable retrieval order make prompt bytes and hashes deterministic for identical inputs/configuration. A temperature of zero does not promise byte-identical provider responses.

## Structured output and abstention

The schema is a closed object with exactly these fields:

```json
{
  "answer": "Revenue was $100 million [C001].",
  "citations": ["C001"],
  "abstained": false
}
```

This example is a synthetic schema illustration, not a model-generated result from the SEC corpus.

A successful abstention must be exactly:

```json
{
  "answer": "Insufficient evidence in the supplied SEC context.",
  "citations": [],
  "abstained": true
}
```

Runtime validation enforces schema keys/types, nonempty answers, unique citation IDs, supplied-context membership, agreement between inline citation markers and the citation list, and consistent abstention state. Duplicate JSON keys, nonfinite JSON constants, fenced/non-JSON output, unknown fields and invalid citations are rejected. A non-abstaining answer requires citations; an abstention cannot contain asserted answers or citations.

Citation grounding rebuilds contexts from the actual retrieved chunks and compares complete text/provenance before resolving references. Citations receive a provenance hash and inspectable source URL/document/chunk linkage. These checks establish source identity and retrieval membership, **not whether the cited text entails every claim**. Semantic citation evaluation and answer-quality scoring belong to Phase 4B.

## Provider behavior and failures

`LLMProvider.generate(prompt, schema, config)` returns a provider-neutral response with raw text, optional usage, response identifier, response model and finish status. The OpenAI adapter translates this to the Responses API with strict JSON-schema output and `store=false`. It uses the fixed official HTTPS endpoint, rejects redirects and keeps the API key out of payloads/traces.

Timeout and connection failures, HTTP 408/429 and server errors can retry with bounded exponential backoff. Authentication/client errors are not retried. The timeout is requests' connection/read timeout per attempt, not a hard end-to-end wall-clock deadline. Retry limits and delays are explicit configuration.

Refused or incomplete responses remain provider errors, preserving returned text. Malformed or invalid structured output is retained as `invalid_output`, never silently accepted and not automatically repaired through additional paid calls. Provider failures and preparation failures are not labeled as model abstentions. Unexpected exception messages and HTTP response bodies are not persisted because they can contain credentials or other sensitive details.

Preparation/retrieval failures produce error traces when a valid LLM configuration is available. Invalid configuration and protected-input integrity errors fail before model execution.

## Traces and offline artifacts

Live/fake-provider execution traces support:

- Question ID/text, retrieval mode/top K, ordered context IDs and full inspectable contexts.
- Retrieval ranks/scores, exact prompt and schema, prompt/config hashes.
- Configured and returned model/provider information.
- Every attempt's raw output, finish status, usage, latency and sanitized error.
- Parsed structured answer, citations, abstention state and citation provenance checks.
- Retrieval, generation-attempt and total latency, optional token usage and final status.

Trace files use content hashes as filenames, so later executions do not overwrite earlier runs. Timing can differ across executions, while prompts remain deterministic. Known credential values and API-key-shaped text are redacted before serialization; secrets are never included in trace configuration. Redaction may replace sensitive substrings in raw output, so stored raw text is not guaranteed to preserve such substrings byte-for-byte.

The four offline prepared files under `evals/generation/phase4a/prepared/` contain real retrieved context and prompts, labeled `prepared_only_no_model_call`. They contain no generated answer, fabricated token usage, or claimed model latency. Their byte content and modification times remain stable on repeat preparation.

## Validation

The complete suite passes: 64 tests, comprising 51 previous tests plus 13 new generation tests. Provider tests use mocks/fakes and do not require `OPENAI_API_KEY`. Tests cover prompt determinism, provenance, output/abstention validation, citation tampering, failure/retry behavior, schema-shaped OpenAI requests, token/latency trace serialization, secret redaction, leakage prevention, configuration/context limits, real BM25/hybrid rank equivalence, offline CLI behavior and protected artifact immutability.

`configs/generation_protected.json` records SHA-256 checksums for 125 existing files under benchmark ground truth, prior retrieval results, parsed documents, chunks, raw SEC filings and ingestion metadata. Inventory and contents are checked before and after CLI execution. New outputs cannot target those protected directories.

## Files created

- `configs/generation.json`: provider, retrieval, prompt, retry, timeout and output settings.
- `configs/generation_protected.json`: immutable prior-artifact inventory and checksums.
- `src/generation/contracts.py`: provider/retriever protocols and validated question/config/response/error contracts.
- `src/generation/providers.py`: OpenAI Responses adapter and provider factory.
- `src/generation/retrieval.py`: section-aware BM25/hybrid integration, read-only dense reuse and integrity checks.
- `src/generation/grounding.py`: context allowlist, deterministic prompt, schema/output/citation validation.
- `src/generation/pipeline.py`: provider-independent orchestration, retry/error handling, latency/usage traces and secret-safe persistence.
- `scripts/run_grounded_generation.py`: four-question sample CLI, offline by default, explicit live option.
- `tests/test_generation.py`: 13 generation infrastructure tests.
- `docs/grounded_generation.md`: this guide, limitations and completion status.
- Four new JSON files in `evals/generation/phase4a/prepared/`: offline sample prompt/context artifacts only.
- `evals/generation/phase4a/validation_report.json`: test count, protected-file verification, configured model, offline sample IDs and explicit zero-live-call status.

No existing code, dependencies, benchmark, chunks, or prior experiment outputs were changed. No commits were made.

## Remaining deferred work

Only the real four-question API demonstration is deferred within Phase 4A: authorize the paid sample, provide `OPENAI_API_KEY` in the runtime environment, make the four generation calls, and inspect/report actual outputs, citation/abstention behavior, measured API latency and token usage. Real provider behavior is not claimed as verified by mocks. The full 100-question generation benchmark and formal answer-quality evaluation are outside this phase and were not run.
