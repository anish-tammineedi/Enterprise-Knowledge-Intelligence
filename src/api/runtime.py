from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time

from src.agentic.document_tool import document_tool
from src.agentic.financial_tool import LocalFinancialData, financial_tool
from src.agentic.orchestrator import Orchestrator
from src.agentic.response import evidence_contexts
from src.agentic.tools import execute_tool
from src.generation.contracts import LLMConfig, ProviderError, Question
from src.generation.grounding import SCHEMA, build_prompt
from src.generation.providers import create_provider
from src.generation.retrieval import SECSectionRetriever
from src.observability.trace import make_trace, inspect_output, privacy_from_config, save_trace


@dataclass
class ServiceFailure(Exception):
    status_code: int
    code: str
    message: str


class Runtime:
    def __init__(self, settings):
        self.settings = settings
        self.config = settings.generation_config()
        self._lock = threading.Lock()
        self._retriever = None
        self._financial = None
        self._provider = None
        self.privacy = privacy_from_config(self.config)

    def document_retriever(self):
        with self._lock:
            if self._retriever is None:
                self._retriever = SECSectionRetriever(self.settings.root, self.config['retrieval'])
            if self.config['retrieval']['mode'] == 'hybrid':
                required = (self._retriever.dense_path / 'sec_section/embeddings.npy',
                            self._retriever.dense_path / 'sec_section/index_manifest.json')
                if not all(path.is_file() for path in required):
                    raise FileNotFoundError('dense retrieval index unavailable')
            return self._retriever

    def financial_data(self):
        with self._lock:
            if self._financial is None:
                cache = self.settings.root / 'data/processed/sec_company_facts'
                if not cache.is_dir() or not list(cache.glob('*.json')):
                    raise FileNotFoundError('financial fact cache unavailable')
                self._financial = LocalFinancialData.from_cache_dir(cache)
                if not any(years for companies in self._financial.facts.values() for years in companies.values()):
                    raise FileNotFoundError('financial fact cache has no accepted rows')
            return self._financial

    def components(self):
        return self.document_retriever(), self.financial_data()

    def provider(self):
        with self._lock:
            if self._provider is None:
                self._provider = create_provider(self.settings.provider)
            return self._provider

    def readiness(self):
        results = {}
        try:
            retriever = self.document_retriever()
            results['document_index'] = {'status': 'available', 'chunks': len(retriever.chunks)}
        except Exception:
            results['document_index'] = {'status': 'unavailable'}
        try:
            cache = self.settings.root / 'data/processed/sec_company_facts'
            files = sorted(cache.glob('*.json'))
            if len(files) < 3:
                raise ValueError()
            facts = self.financial_data()
            count = sum(len(rows) for years in facts.facts.values() for metrics in years.values() for rows in metrics.values())
            if count < 1:
                raise ValueError()
            results['financial_facts'] = {'status': 'available', 'cache_files': len(files), 'accepted_facts': count}
        except Exception:
            results['financial_facts'] = {'status': 'unavailable'}
        results['ollama'] = self.ollama_status()
        ready = all(results[name]['status'] == 'available' for name in ('document_index', 'financial_facts'))
        return {'status': 'ready' if ready else 'not_ready', 'components': results}

    def ollama_status(self):
        from src.generation.ollama import local_endpoint
        try:
            endpoint = local_endpoint(self.settings.ollama_base_url)
        except ValueError:
            return {'status': 'misconfigured', 'optional': True}
        try:
            import requests
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(endpoint + '/api/tags', timeout=min(1.5, self.settings.request_timeout_seconds))
                response.raise_for_status()
                models = response.json().get('models', [])
            available = any(m.get('name') == self.settings.ollama_model or m.get('model') == self.settings.ollama_model for m in models)
            return {'status': 'available' if available else 'model_unavailable', 'optional': True,
                    'model': self.settings.ollama_model}
        except Exception:
            return {'status': 'unavailable', 'optional': True, 'model': self.settings.ollama_model}

    def retrieve(self, query, mode=None, top_k=None):
        try:
            retriever = self.document_retriever()
        except FileNotFoundError:
            raise ServiceFailure(503, 'local_artifacts_unavailable', 'Required local artifacts are unavailable') from None
        try:
            tool = document_tool(retriever, {'mode': mode or self.config['retrieval']['mode'],
                                             'top_k': top_k or self.config['retrieval']['top_k']})
            payload = {'query': query}
            if mode is not None: payload['mode'] = mode
            if top_k is not None: payload['top_k'] = top_k
            result = execute_tool(tool, payload)
        except Exception:
            raise ServiceFailure(500, 'internal_failure', 'Request could not be completed') from None
        if result.status == 'invalid_input':
            raise ServiceFailure(422, 'invalid_request', 'Retrieval parameters are invalid')
        if result.status == 'error':
            raise ServiceFailure(503, 'retrieval_failure', 'Document retrieval is unavailable')
        return result

    def run_query(self, query, trace_id):
        started = time.perf_counter()
        config = self.config
        router = Orchestrator(None, None)
        selected, _ = router.route(query)
        try:
            retriever = self.document_retriever() if 'document_retrieval' in selected else None
            financial = self.financial_data() if 'financial_data' in selected else None
        except FileNotFoundError:
            raise ServiceFailure(503, 'local_artifacts_unavailable', 'Required local artifacts are unavailable') from None
        tools = {'document_retrieval': document_tool(retriever, config['retrieval']) if retriever is not None else None,
                 'financial_data': financial_tool(financial) if financial is not None else None}
        orchestrator = Orchestrator(tools['document_retrieval'], tools['financial_data'])
        orchestration = orchestrator.execute(query)
        route = orchestration['selected_tools']
        generation = {'contexts': [], 'raw_model_output': None, 'status': 'not_run',
                      'token_usage': None, 'generation_latency_seconds': None}
        retrieved = [e for tool in orchestration['tool_results'] if tool['tool_name'] == 'document_retrieval' for e in tool['evidence']]
        if route:
            generation['contexts'] = evidence_contexts(orchestration)
            prompt = build_prompt(Question(trace_id, query), generation['contexts'], config['prompt'])
            call_start = time.perf_counter()
            try:
                response = self.provider().generate(prompt, SCHEMA, LLMConfig(**config['llm']))
                generation.update(raw_model_output=response.text, token_usage=response.usage,
                                  status='success' if response.finish_status == 'completed' else 'incomplete_output')
            except ProviderError as exc:
                generation.update(status='provider_error', error={'code': exc.code, 'status_code': exc.status_code,
                                                                  'retryable': exc.retryable})
            except Exception:
                generation.update(status='generation_error', error={'code': 'unexpected_provider_error'})
            generation['generation_latency_seconds'] = time.perf_counter() - call_start
        else:
            from src.generation.grounding import ABSTENTION
            generation.update(status='skipped_unsupported', raw_model_output=json.dumps({'answer': ABSTENTION, 'citations': [], 'abstained': True}),
                              token_usage={'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}, generation_latency_seconds=0)

        validation_start = time.perf_counter()
        validation, _ = inspect_output(generation['raw_model_output'], generation['contexts'], generation['contexts'])
        generation['validation_latency_seconds'] = time.perf_counter() - validation_start
        if generation['status'] == 'success' and validation['output_contract_valid'] is False:
            generation['status'] = 'invalid_output'
            generation['error'] = {'code': 'invalid_output', 'detail': validation['details'][0] if validation['details'] else 'validation_failed'}
        document_result = next((item for item in orchestration['tool_results'] if item['tool_name'] == 'document_retrieval'), None)
        financial_result = next((item for item in orchestration['tool_results'] if item['tool_name'] == 'financial_data'), None)
        document_sufficient = False if document_result is not None and not document_result['evidence'] else None
        if document_result is None:
            evidence_sufficient = financial_result['status'] == 'success' if financial_result is not None else None
        elif financial_result is not None and (document_sufficient is False or financial_result['status'] != 'success'):
            evidence_sufficient = False
        elif document_sufficient is False:
            evidence_sufficient = False
        else:
            evidence_sufficient = None
        trace = make_trace(trace_id, query, config, orchestration, generation,
                           {'sufficiency_basis': 'no_document_evidence_returned' if document_sufficient is False else None,
                            'document_evidence_sufficient': document_sufficient,
                            'evidence_sufficient': evidence_sufficient},
                           trace_id=trace_id, timestamp=datetime.now(timezone.utc).isoformat(),
                           privacy=self.privacy)
        trace['latency']['end_to_end_seconds'] = time.perf_counter() - started
        trace['latency']['recorded_seconds'] = trace['latency']['end_to_end_seconds']
        trace['latency']['recorded_scope'] = 'query_to_validated_result_excluding_trace_disk_write'
        trace['retrieval']['latency_seconds'] = orchestration.get('retrieval_latency_seconds')
        trace['validation']['latency_seconds'] = generation['validation_latency_seconds']
        if generation['raw_model_output'] is not None and validation['output_contract_valid']:
            output = json.loads(generation['raw_model_output'])
            trace['result']['citations'] = output['citations']
        self.save(trace)
        if generation['status'] in ('provider_error', 'generation_error', 'incomplete_output'):
            code = generation.get('error', {}).get('code')
            if code == 'timeout':
                raise ServiceFailure(504, 'timeout', 'Generation timed out')
            raise ServiceFailure(503, 'generation_backend_unavailable', 'Generation backend is unavailable')
        if any(t['status'] in ('error', 'invalid_input') for t in orchestration['tool_results']):
            raise ServiceFailure(503, 'tool_failure', 'A requested tool could not complete')
        if generation['status'] == 'invalid_output':
            raise ServiceFailure(502, 'invalid_output', 'Generation output failed validation')
        answer = json.loads(generation['raw_model_output']) if generation['raw_model_output'] else None
        if answer is None:
            raise ServiceFailure(500, 'internal_failure', 'Request could not be completed')
        context_by_id = {c['context_id']: c for c in generation['contexts']}
        citations = []
        for context_id in answer['citations']:
            context = context_by_id[context_id]
            citations.append({'context_id': context_id, 'chunk_id': context['chunk_id'],
                              'document_id': context['document_id'], 'ticker': context['ticker'],
                              'accession_number': context['accession_number'], 'source_url': context['source_url']})
        return trace, answer, generation['contexts'], citations

    def save(self, trace):
        self.settings.trace_dir.mkdir(parents=True, exist_ok=True)
        save_trace(self.settings.trace_dir / (trace['trace_id'] + '.json'), trace)
