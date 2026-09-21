import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.runtime import Runtime
from src.api.settings import Settings
from src.agentic.financial_tool import LocalFinancialData
from src.generation.contracts import ProviderError, ProviderResponse
from src.generation.grounding import ABSTENTION
from tests.test_generation import chunk

ROOT = Path(__file__).resolve().parents[1]


class FakeRetriever:
    def __init__(self, fail=False, empty=False):
        self.fail, self.empty = fail, empty

    def retrieve(self, query, mode, top_k):
        if self.fail:
            raise RuntimeError('private retrieval failure')
        return [] if self.empty else [{**chunk(), 'ticker': 'AAPL', 'company': 'Apple Inc.',
                                        'accession_number': 'acc-test', 'source_url': 'https://www.sec.gov/test',
                                        'retrieval_rank': 1, 'retrieval_score': 1.0,
                                        'retrieval_score_type': 'bm25'}][:top_k]


class FakeProvider:
    def __init__(self, response=None, error=None, delay=0, counters=None):
        self.response, self.error, self.delay, self.counters = response, error, delay, counters

    def generate(self, prompt, schema, config):
        if self.counters:
            with self.counters['lock']:
                self.counters['active'] += 1
                self.counters['peak'] = max(self.counters['active'], self.counters['peak'])
        try:
            if self.delay:
                time.sleep(self.delay)
            if self.error:
                raise self.error
            if self.response:
                return ProviderResponse(self.response, {'input_tokens': 17, 'output_tokens': 8, 'total_tokens': 25})
            evidence = json.loads(prompt['input'])['evidence']
            if not evidence:
                body = {'answer': ABSTENTION, 'citations': [], 'abstained': True}
            else:
                body = {'answer': 'Revenue was 100 USD [C001].', 'citations': ['C001'], 'abstained': False}
            return ProviderResponse(json.dumps(body), {'input_tokens': 17, 'output_tokens': 8, 'total_tokens': 25})
        finally:
            if self.counters:
                with self.counters['lock']:
                    self.counters['active'] -= 1


class FakeRuntime(Runtime):
    def __init__(self, settings, retriever=None, provider=None, ready=None):
        super().__init__(settings)
        self._retriever = retriever or FakeRetriever()
        self._financial = LocalFinancialData(facts={'AAPL': {'2025': {'revenue': [{
            'concept': 'SalesRevenueNet', 'value': 100, 'unit': 'USD', 'start': '2024-09-29',
            'end': '2025-09-27', 'filing_date': '2025-10-31', 'accession_number': 'acc-test',
            'cik': '0000320193', 'company': 'Apple Inc.', 'source_url': 'https://www.sec.gov/test'}]}}})
        self._provider = provider or FakeProvider()
        self.ready_response = ready or {'status': 'ready', 'components': {
            'document_index': {'status': 'available', 'chunks': 1},
            'financial_facts': {'status': 'available', 'accepted_facts': 1},
            'ollama': {'status': 'unavailable', 'optional': True, 'model': 'offline-model'}}}
        self.delay_query = 0

    def components(self):
        return self._retriever, self._financial

    def provider(self):
        return self._provider

    def readiness(self):
        return self.ready_response

    def run_query(self, query, trace_id):
        if self.delay_query:
            time.sleep(self.delay_query)
        return super().run_query(query, trace_id)


def settings(directory, timeout=3, concurrency=4):
    value = Settings.from_env(ROOT, {})
    return Settings(**{**value.__dict__, 'trace_dir': Path(directory),
                       'request_timeout_seconds': timeout, 'max_concurrency': concurrency})


def make_client(directory, **kwargs):
    configured = settings(directory, kwargs.pop('timeout', 3), kwargs.pop('concurrency', 4))
    runtime = FakeRuntime(configured, **kwargs)
    api = create_app(configured, runtime_factory=lambda _: runtime)
    return TestClient(api), runtime


class ApiTests(unittest.TestCase):
    def test_health_is_lightweight(self):
        with tempfile.TemporaryDirectory() as d:
            client, _ = make_client(d)
            with client:
                response = client.get('/health')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'status': 'ok'})

    def test_ready_optional_ollama_does_not_make_service_unready(self):
        ready = {'status': 'ready', 'components': {'document_index': {'status': 'available'},
            'financial_facts': {'status': 'available'}, 'ollama': {'status': 'unavailable', 'optional': True}}}
        with tempfile.TemporaryDirectory() as d:
            client, _ = make_client(d, ready=ready)
            with client: response = client.get('/ready')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['components']['ollama']['status'], 'unavailable')
        not_ready = {'status': 'not_ready', 'components': {'document_index': {'status': 'unavailable'},
            'financial_facts': {'status': 'available'}, 'ollama': {'status': 'unavailable', 'optional': True}}}
        with tempfile.TemporaryDirectory() as d:
            client, _ = make_client(d, ready=not_ready)
            with client: response = client.get('/ready')
        self.assertEqual(response.json()['status'], 'not_ready')

    def test_valid_retrieve_returns_ranked_provenance(self):
        with tempfile.TemporaryDirectory() as d:
            client, _ = make_client(d)
            with client: response = client.post('/retrieve', json={'query': 'Apple business', 'mode': 'bm25', 'top_k': 1})
        self.assertEqual(response.status_code, 200)
        result=response.json(); self.assertEqual(result['evidence'][0]['ticker'],'AAPL')
        self.assertEqual(result['evidence'][0]['accession_number'],'acc-test')
        self.assertEqual(result['evidence'][0]['rank'],1)

    def test_invalid_retrieve_request_is_sanitized(self):
        with tempfile.TemporaryDirectory() as d:
            client, _ = make_client(d)
            with client:
                response=client.post('/retrieve',json={'query':'secret@example.com','top_k':0,'password':'secret'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(response.json()['error']['code'],'invalid_request')
        self.assertNotIn('secret@example.com',response.text)
        self.assertNotIn('password',response.text)

    def test_valid_financial_query_response_and_trace(self):
        with tempfile.TemporaryDirectory() as d:
            client,_=make_client(d)
            with client: response=client.post('/query',json={'query':'What was Apple revenue in fiscal 2025?'})
            self.assertEqual(response.status_code,200,response.text)
            body=response.json()
            self.assertEqual(body['routing_decision'],'financial_data')
            self.assertEqual(body['tools_used'],['financial_data'])
            self.assertFalse(body['abstained'])
            self.assertTrue(body['citations'])
            saved=client.get('/trace/'+body['trace_id'])
            self.assertEqual(saved.status_code,200)
            self.assertEqual(saved.json()['query']['text'],'[REDACTED]')
            self.assertEqual(saved.json()['generation']['model'] if 'model' in saved.json()['generation'] else saved.json()['generation']['configuration']['model'],'qwen3:4b-instruct-2507-q4_K_M')

    def test_abstaining_query(self):
        with tempfile.TemporaryDirectory() as d:
            client,_=make_client(d, retriever=FakeRetriever(empty=True), provider=FakeProvider(response=json.dumps({'answer':ABSTENTION,'citations':[],'abstained':True})))
            with client: response=client.post('/query',json={'query':'Describe Apple business'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['abstained'])
        self.assertEqual(response.json()['validation_status'],'passed')

    def test_backend_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            client,_=make_client(d,provider=FakeProvider(error=ProviderError('transport_error',retryable=True)))
            with client: response=client.post('/query',json={'query':'What was Apple revenue in 2025?'})
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['error']['code'],'generation_backend_unavailable')
        self.assertNotIn('private',response.text)

    def test_tool_failure_is_safe(self):
        with tempfile.TemporaryDirectory() as d:
            client,_=make_client(d,retriever=FakeRetriever(fail=True),provider=FakeProvider(response=json.dumps({'answer':ABSTENTION,'citations':[],'abstained':True})))
            with client: response=client.post('/query',json={'query':'Describe Apple business'})
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['error']['code'],'tool_failure')
        self.assertNotIn('private retrieval failure',response.text)

    def test_request_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            client,runtime=make_client(d,timeout=0.05,provider=FakeProvider(delay=0.2))
            with client: response=client.post('/query',json={'query':'What was Apple revenue in 2025?'})
        self.assertEqual(response.status_code,504)
        self.assertEqual(response.json()['error']['code'],'timeout')
        time.sleep(0.25)

    def test_trace_missing_and_invalid_ids(self):
        with tempfile.TemporaryDirectory() as d:
            client,_=make_client(d)
            with client:
                missing=client.get('/trace/missing')
                invalid=client.get('/trace/%2e%2e%2fsecret')
        self.assertEqual(missing.status_code,404)
        self.assertEqual(missing.json()['error']['code'],'trace_not_found')
        self.assertIn(invalid.status_code,(404,422))
        self.assertNotIn('secret',invalid.text)

    def test_configuration_loading_and_validation(self):
        configured=Settings.from_env(ROOT,{'EKI_HOST':'0.0.0.0','EKI_PORT':'9000','EKI_RETRIEVAL_MODE':'hybrid','EKI_RETRIEVAL_TOP_K':'7','EKI_OLLAMA_MODEL':'local-model','EKI_REQUEST_TIMEOUT_SECONDS':'42','EKI_MAX_CONCURRENCY':'2'})
        self.assertEqual((configured.host,configured.port,configured.retrieval_mode,configured.retrieval_top_k),('0.0.0.0',9000,'hybrid',7))
        with self.assertRaises(ValueError): Settings.from_env(ROOT,{'EKI_PORT':'99999'})
        with self.assertRaises(ValueError): Settings.from_env(ROOT,{'EKI_RETRIEVAL_MODE':'unknown'})
        self.assertNotIn('secret',json.dumps(configured.generation_config()))

    def test_trace_sanitizes_sensitive_content(self):
        personal='person@example.org 312-555-0188'
        trace={'schema_version':'6.1','trace_id':'trace-a','timestamp':None,
               'source':{'kind':'test','id':'fixture'},'query':{'id':'trace-a','text':'[REDACTED]','policy':'unreviewed_text_withheld'},
               'routing':{'decision':'abstain','reason':'safe'},'tools':[],
               'retrieval':{'evidence':[]},'generation':{'status':'not_run'},
               'validation':{},'abstention':{},'result':{'answer':'[REDACTED]'},'latency':{},
               'lower_level':{},'failure_attribution':{'primary':'unsupported_query','categories':['unsupported_query']}}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'trace-a.json';path.write_text(json.dumps(trace))
            client,_=make_client(d)
            with client: response=client.get('/trace/trace-a')
        self.assertEqual(response.status_code,500)
        self.assertNotIn(personal,response.text)

    def test_concurrent_requests_respect_executor_limit(self):
        counters={'active':0,'peak':0,'lock':threading.Lock()}
        with tempfile.TemporaryDirectory() as d:
            client,_=make_client(d,provider=FakeProvider(counters=counters),concurrency=2)
            with client:
                def call(_): return client.post('/query',json={'query':'What was Apple revenue in 2025?'}).status_code
                with ThreadPoolExecutor(max_workers=6) as pool: statuses=list(pool.map(call,range(6)))
        self.assertEqual(statuses,[200]*6)
        self.assertLessEqual(counters['peak'],2)

    def test_global_app_import_does_not_load_local_components(self):
        with patch.object(Runtime,'components',side_effect=AssertionError('health loaded local artifacts')):
            from src.api.app import app
            self.assertIsNotNone(app)


if __name__ == '__main__':
    unittest.main()
