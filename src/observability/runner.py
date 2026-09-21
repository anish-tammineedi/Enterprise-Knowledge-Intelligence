from copy import deepcopy
from datetime import datetime, timezone
import json
import time
from uuid import uuid4

from src.agentic.document_tool import document_tool
from src.agentic.financial_tool import financial_tool
from src.agentic.orchestrator import Orchestrator
from src.agentic.response import evidence_contexts
from src.generation.contracts import LLMConfig, ProviderError, Question
from src.generation.grounding import ABSTENTION, SCHEMA, build_prompt
from src.observability.trace import classify, inspect_output, make_trace, privacy_from_config


class TimedRetriever:
    def __init__(self, retriever, clock):
        self.retriever, self.clock = retriever, clock
        self.seconds = None

    def retrieve(self, *args):
        started = self.clock()
        try:
            return self.retriever.retrieve(*args)
        finally:
            self.seconds = self.clock() - started


class TimedOrchestrator(Orchestrator):
    def __init__(self, document, financial, clock):
        super().__init__(document, financial)
        self.clock, self.routing_seconds = clock, None

    def route(self, query):
        started = self.clock()
        try:
            return super().route(query)
        finally:
            self.routing_seconds = self.clock() - started


def run_query(query, retriever, data, provider, config, labels=None, privacy=None,
              clock=time.perf_counter, timestamp=None, trace_id=None):
    started = clock()
    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    trace_id = trace_id or str(uuid4())
    privacy = privacy or privacy_from_config(config)
    labels = dict(labels or {})
    timed = TimedRetriever(retriever, clock)
    orchestrator = TimedOrchestrator(document_tool(timed, config['retrieval']), financial_tool(data), clock)
    generation = {'contexts': [], 'status': 'not_run', 'raw_model_output': None}
    routing_error = None
    try:
        orchestration = orchestrator.execute(query)
    except Exception:
        routing_error = {'code': 'routing_execution_error'}
        orchestration = {'status': 'routing_error'}
    if routing_error is None:
        try:
            generation['contexts'] = evidence_contexts(orchestration)
            prompt = build_prompt(Question(trace_id, query), generation['contexts'], config['prompt'])
        except Exception:
            generation.update(status='preparation_error', error={'code': 'context_preparation_failed'})
        else:
            if not orchestration['selected_tools']:
                labels.setdefault('expected_abstention', True)
                generation.update(status='skipped_unsupported', raw_model_output=json.dumps({'answer': ABSTENTION, 'citations': [], 'abstained': True}),
                                  token_usage={'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}, generation_latency_seconds=0)
            else:
                t0 = clock()
                try:
                    response = provider.generate(deepcopy(prompt), deepcopy(SCHEMA), LLMConfig(**config['llm']))
                    generation.update(raw_model_output=response.text, token_usage=response.usage,
                                      status='success' if response.finish_status == 'completed' else 'incomplete_output')
                except ProviderError as error:
                    generation.update(status='provider_error', error={'code': error.code, 'retryable': error.retryable, 'status_code': error.status_code})
                except Exception:
                    generation.update(status='generation_error', error={'code': 'unexpected_provider_error'})
                generation['generation_latency_seconds'] = clock() - t0
    validation_start = clock()
    validation, _ = inspect_output(generation.get('raw_model_output'), generation['contexts'])
    validation_seconds = clock() - validation_start
    if generation['status'] == 'success' and validation['output_contract_valid'] is False:
        generation['status'] = 'invalid_output'
        generation['error'] = {'code': 'invalid_output', 'detail': validation['details'][0] if validation['details'] else 'validation_failed'}
    doc = next((t for t in orchestration.get('tool_results', []) if t['tool_name'] == 'document_retrieval'), None)
    if doc is not None and not doc['evidence']:
        labels.setdefault('document_evidence_sufficient', False)
        labels.setdefault('sufficiency_basis', 'no_document_evidence_returned')
    financial = next((t for t in orchestration.get('tool_results', []) if t['tool_name'] == 'financial_data'), None)
    if doc is None and financial is not None:
        labels.setdefault('evidence_sufficient', financial['status'] == 'success')
    if doc is not None and labels.get('document_evidence_sufficient') is False:
        labels.setdefault('evidence_sufficient', False)
    trace = make_trace(trace_id, query, config, orchestration, generation, labels, timestamp, trace_id, privacy)
    trace['lower_level']['routing_error'] = routing_error
    trace['routing']['latency_seconds'] = orchestrator.routing_seconds
    trace['retrieval']['latency_seconds'] = timed.seconds
    trace['retrieval']['latency_source'] = 'measured_retriever_call' if timed.seconds is not None else None
    trace['validation']['latency_seconds'] = validation_seconds
    trace['result']['citations'] = json.loads(generation['raw_model_output'])['citations'] if validation['output_contract_valid'] is True else []
    trace['latency']['end_to_end_seconds'] = clock() - started
    trace['latency']['recorded_seconds'] = trace['latency']['end_to_end_seconds']
    trace['latency']['recorded_scope'] = 'query_to_validated_result_excluding_disk_write'
    return privacy.clean(classify(trace))
