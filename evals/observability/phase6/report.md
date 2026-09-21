# Phase 6 historical evaluation and observability

No generation or network calls were made. This selection includes the 20 Phase 4B evaluated executions and the four final Phase 5 executions. Superseded Phase 5 runs and unrelated Phase 4A failures are excluded. Existing source artifacts are unchanged.

## Aggregate metrics

| Metric | Phase 4B | Phase 5 | Combined |
|---|---|---|---|
| routing_success_rate | unavailable | 100.00% (4/4; 0 unavailable) | 100.00% (4/4; 20 unavailable) |
| tool_success_rate | unavailable | 100.00% (4/4; 0 unavailable) | 100.00% (4/4; 0 unavailable) |
| retrieval_evidence_sufficiency_rate | 38.89% (7/18; 2 unavailable) | 0.00% (0/2; 0 unavailable) | 35.00% (7/20; 2 unavailable) |
| structured_output_validity | 100.00% (20/20; 0 unavailable) | 100.00% (4/4; 0 unavailable) | 100.00% (24/24; 0 unavailable) |
| output_contract_validity | 90.00% (18/20; 0 unavailable) | 75.00% (3/4; 0 unavailable) | 87.50% (21/24; 0 unavailable) |
| abstention_rate | 50.00% (10/20; 0 unavailable) | 50.00% (2/4; 0 unavailable) | 50.00% (12/24; 0 unavailable) |
| expected_abstention_accuracy | 100.00% (2/2; 0 unavailable) | 66.67% (2/3; 0 unavailable) | 80.00% (4/5; 0 unavailable) |
| abstention_label_accuracy | 60.00% (12/20; 0 unavailable) | 75.00% (3/4; 0 unavailable) | 62.50% (15/24; 0 unavailable) |
| citation_validation_rate | 90.00% (18/20; 0 unavailable) | 75.00% (3/4; 0 unavailable) | 87.50% (21/24; 0 unavailable) |

Sufficiency is not inferred from nonempty retrieval. Phase 4B uses coverage of every required benchmark evidence ID under the existing overlap matcher; this is a benchmark-coverage proxy, not proof that an answer is supported. Phase 5 reuses the saved reviewed sufficiency labels. They are also separated by basis in aggregate JSON. Unanswerable benchmark questions have no positive evidence-sufficiency target.

Structured-output validity measures JSON fields and types. Output-contract validity also checks citations and abstention rules. Citation validity is syntactic membership/provenance validation, not semantic claim entailment. Valid abstentions with no citations count as citation-valid.

Expected-abstention accuracy uses only cases labeled as requiring abstention. Abstention-label accuracy compares both positive and negative labels. Phase 4B labels reflect benchmark answerability; Phase 5 labels reflect the reviewed returned evidence, so the combined rate mixes those two evaluation scopes.

## Latencies and tokens

| Stage | Known samples | Mean seconds | Median seconds | p95 seconds |
|---|---:|---:|---:|---:|
| end_to_end | 2 | 9.332703 | 9.332703 | 15.236229 |
| retrieval | 20 | 0.002813 | 0.001686 | 0.006394 |
| generation | 24 | 15.401709 | 15.259440 | 23.911329 |

Only the two new Phase 5 financial executions have recorded timing spanning orchestration, preparation, generation, and validation. The other 22 end-to-end latencies remain unavailable. All 24 recorded generation-pipeline durations are preserved by their actual scope in aggregate JSON. Historical Phase 5 retrieval latency was not separately timed; document-tool latency remains available as tool timing, not mislabeled retrieval timing. Historical routing and validation-stage times and timestamps are unavailable. p95 uses nearest rank.

| Tokens | Known sum | Known mean | Missing executions |
|---|---:|---:|---:|
| input_tokens | 100656 | 4194 | 0 |
| output_tokens | 1730 | 72.08333333333333 | 0 |
| total_tokens | 102386 | 4266.083333333333 | 0 |

All-query totals/averages become null if any execution has unknown token usage. Known sums and coverage remain available. Input/output totals may determine total_tokens when the provider did not report it; conflicting supplied totals are unavailable.

## Failure attribution

| Category | Primary | All occurrences |
|---|---:|---:|
| success | 6 | 6 |
| expected_abstention | 2 | 4 |
| unsupported_query | 1 | 1 |
| retrieval_failure | 12 | 12 |
| tool_failure | 0 | 0 |
| routing_failure | 0 | 0 |
| generation_failure | 0 | 1 |
| citation_failure | 2 | 3 |
| invalid_output | 0 | 3 |
| partial_evidence | 1 | 1 |

Primary attribution is exclusive and uses documented precedence. All occurrences preserve simultaneous failures; their counts need not sum to total queries. The combined Phase 5 execution remains partial_evidence plus generation_failure, citation_failure, and invalid_output. Earlier heuristic attributions are retained under lower_level.legacy_evaluation and are not silently promoted to measured semantic correctness.

## Selected executions

| Query ID | Source | Primary attribution | Output contract | Trace |
|---|---|---|---|---|
| SEC-001 | phase4b | retrieval_failure | True | [JSON](traces/b70c0d7019e74b79d1b4e81d2b50904c619982fd643e1ab6b33a4eb644cc2991.json) |
| SEC-002 | phase4b | success | True | [JSON](traces/0e33c6dd61646163f21973c011439d24ae2b70a43fbea2f1cb485f72b284d581.json) |
| SEC-011 | phase4b | success | True | [JSON](traces/66dfe7d351fe15a596f4a105d076b2e8c729dfbf3655485b46b01d4f284306e5.json) |
| SEC-012 | phase4b | retrieval_failure | True | [JSON](traces/126136a724a697020ad7e63f19e383a1a4c8dd62afe8bc3e620d21888eb8091e.json) |
| SEC-021 | phase4b | retrieval_failure | True | [JSON](traces/647471b4043c7a4f8e2deeda3d24c511a16dde7fcde8ab1187f5be8bac31dc5b.json) |
| SEC-022 | phase4b | success | True | [JSON](traces/b3c9a7cb992b8690af2a6a15f34071985aa3332cb4ae502f06312fb465f0d9f5.json) |
| SEC-031 | phase4b | success | True | [JSON](traces/27d4b14f33365116cde7f7987e0d113e0a0accfe66eb37f512ccd4989bd4cfa0.json) |
| SEC-032 | phase4b | citation_failure | False | [JSON](traces/cd91306ce1ccd7ebe0e7de2e7ae79c7733164fa840f062e10ff5d8e1d0ba61b0.json) |
| SEC-041 | phase4b | retrieval_failure | True | [JSON](traces/c7fb51214bd72bb55da987c1828a75f6b13d2dee6511e7c13ea93366ac1a8fe2.json) |
| SEC-042 | phase4b | retrieval_failure | True | [JSON](traces/585361504b04d2e023312d7aeda640e06d73dd1b9651a46385476eab9be5ecb4.json) |
| SEC-051 | phase4b | retrieval_failure | True | [JSON](traces/fe52a70d90c729ce5299302c4e9387f59e3ceb094661c095fb20c07196fb29c1.json) |
| SEC-052 | phase4b | retrieval_failure | True | [JSON](traces/1cde7f09a1533d09a3b12bbdb80a0eaf6c438b1eb951c177898461dbefba9170.json) |
| SEC-061 | phase4b | citation_failure | False | [JSON](traces/90ffb4cb4ab65f916aa52f455e88ee276fae27166c657ff2422eae119a9847ea.json) |
| SEC-062 | phase4b | retrieval_failure | True | [JSON](traces/040a07500bfca97a97ca4f825bf08119022fa7442e591171de055105b6428948.json) |
| SEC-071 | phase4b | success | True | [JSON](traces/b12841d8fc3780f4e03516e865873d788f04d58649562d14a2944b2b4bba3def.json) |
| SEC-072 | phase4b | retrieval_failure | True | [JSON](traces/b1dd38633c27dd898fbc4392b4682923ea586e1f3ef8f93a3b04c0647d57102c.json) |
| SEC-081 | phase4b | expected_abstention | True | [JSON](traces/d0cba23f11e90ce2f57f913bc51e56b6134a57b7a6b1b172814a2ce26e91daa5.json) |
| SEC-082 | phase4b | expected_abstention | True | [JSON](traces/22dacf159bff5b9bee74380d01ec7b50f7b890973915903488d4aa6970abc4d3.json) |
| SEC-091 | phase4b | retrieval_failure | True | [JSON](traces/6c547b3f776ca6371e3a47f993cfbcc631768ab2d2eee5921b2025e28f4ae476.json) |
| SEC-092 | phase4b | retrieval_failure | True | [JSON](traces/994a37ffc88496bf4fa5f1dd2e7ec8ae5d8877de564a19d35e2dfb92d3487b91.json) |
| P5-ABSTAIN-001 | phase5 | unsupported_query | True | [JSON](traces/b5c6bb97d6d93933e6b8ce23e5aac2c6f214de8167b503cc59a4b5203bcaea6d.json) |
| P5-BOTH-001 | phase5 | partial_evidence | False | [JSON](traces/8a3c5ccbb33b435947bc0dbf0815fb3f4de038c9a8ed6f414eed45b9fc43498c.json) |
| P5-DOC-001 | phase5 | retrieval_failure | True | [JSON](traces/67023c676452b6e00bdbc9949853e18da4989c583af49534d0012ccb8bb6dc76.json) |
| P5-FIN-001 | phase5 | success | True | [JSON](traces/5b5a874157af744918bd98545c259da62b4d419148e5e45cf55388d45f349ca7.json) |

## Privacy and limits

Query IDs identify the source questions. Unreviewed query text, prompts, evidence text, raw answers, arbitrary exception details, credentials, environment fields, and personal fields are not copied into unified logs. Only allowlisted operational configuration and SEC evidence metadata are retained. Approved public query text can be provided explicitly to the runtime privacy policy; names and addresses require that review because regex matching alone cannot guarantee PII removal.

This is an offline historical evaluation, not a new model-quality experiment. Routing has labels only for Phase 5. Phase 4B has no routing/tool records. Semantic groundedness is not inferred from a valid JSON response or citation. Missing observations are null with explicit denominators, never zero-filled.
