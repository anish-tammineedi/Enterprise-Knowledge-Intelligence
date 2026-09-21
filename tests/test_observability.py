from prepared_artifacts import require_prepared_artifacts
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.agentic.financial_tool import LocalFinancialData
from src.generation.contracts import ProviderResponse, ProviderError
from src.generation.grounding import ABSTENTION
from src.observability.aggregate import aggregate
from src.observability.historical import import_phase4b, import_phase5
from src.observability.runner import run_query
from src.observability.trace import Privacy, make_trace, save_trace, serialize, inspect_output
from tests.test_generation import chunk

ROOT = Path(__file__).resolve().parents[1]


def config():
    return json.loads((ROOT / 'configs/generation_ollama.json').read_text())


def data():
    return LocalFinancialData(facts={'AAPL': {'2025': {'revenue': [{'concept': 'SalesRevenueNet', 'value': 100,
        'unit': 'USD', 'end': '2025-09-27', 'filing_date': '2025-10-31', 'accession_number': 'a'}]}}})


class Retriever:
    def __init__(self, fail=False, empty=False):
        self.fail, self.empty = fail, empty

    def retrieve(self, *args):
        if self.fail:
            raise RuntimeError('private retrieval detail')
        return [] if self.empty else [chunk()]


class Provider:
    def __init__(self, raw=None, fail=False):
        self.raw = raw or json.dumps({'answer': 'Revenue was 100 USD [C001].', 'citations': ['C001'], 'abstained': False})
        self.fail, self.calls = fail, 0

    def generate(self, *args):
        self.calls += 1
        if self.fail:
            raise ProviderError('timeout', retryable=True)
        return ProviderResponse(self.raw, {'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30})


def abstention():
    return json.dumps({'answer': ABSTENTION, 'citations': [], 'abstained': True})


def run(query='What was Apple revenue in 2025?', **kwargs):
    return run_query(query, kwargs.pop('retriever', Retriever()), kwargs.pop('data', data()),
                     kwargs.pop('provider', Provider()), config(), **kwargs)


class ObservabilityTests(unittest.TestCase):
    def test_successful_financial_flow(self):
        t = run(labels={'expected_tools': ['financial_data']})
        self.assertEqual(t['failure_attribution']['primary'], 'success')
        self.assertEqual(t['routing']['tools_selected'], ['financial_data'])
        self.assertTrue(t['routing']['correct'])
        self.assertEqual(t['tools'][0]['evidence'][0]['value'], 100)
        self.assertIsNone(t['retrieval']['latency_seconds'])
        self.assertTrue(t['validation']['output_contract_valid'])
        self.assertEqual(t['generation']['token_usage']['total_tokens'], 30)
        self.assertGreaterEqual(t['latency']['end_to_end_seconds'], t['generation']['latency_seconds'])
        self.assertIsNotNone(t['timestamp'])

    def test_document_flow_does_not_infer_sufficiency(self):
        t = run('Describe Apple business', labels={'expected_tools': ['document_retrieval']})
        self.assertEqual(t['tools'][0]['name'], 'document_retrieval')
        self.assertIsNone(t['retrieval']['evidence_sufficient'])
        self.assertEqual(t['retrieval']['evidence'][0]['chunk_id'], 'chunk-a')
        self.assertIsNotNone(t['retrieval']['latency_seconds'])
        self.assertIsNotNone(t['routing']['latency_seconds'])

    def test_combined_flow(self):
        t = run('What was Apple revenue in 2025 and why did it change?', labels={'expected_tools': ['document_retrieval', 'financial_data'], 'document_evidence_sufficient': True, 'sufficiency_basis': 'test_label'})
        self.assertEqual(len(t['tools']), 2)
        self.assertEqual(t['failure_attribution']['primary'], 'success')

    def test_expected_abstention(self):
        t = run('Describe Apple business', retriever=Retriever(empty=True), provider=Provider(abstention()), labels={'expected_abstention': True})
        self.assertIn('expected_abstention', t['failure_attribution']['categories'])
        self.assertTrue(t['abstention']['correct'])
        self.assertFalse(t['retrieval']['evidence_sufficient'])

    def test_unsupported_query_skips_provider(self):
        p = Provider()
        t = run('What is the stock price?', provider=p)
        self.assertEqual(p.calls, 0)
        self.assertEqual(t['failure_attribution']['primary'], 'unsupported_query')
        self.assertEqual(t['tools'], [])
        self.assertTrue(t['validation']['output_contract_valid'])

    def test_retrieval_failure_preserves_error(self):
        t = run('Describe Apple business', retriever=Retriever(fail=True), provider=Provider(abstention()))
        self.assertEqual(t['failure_attribution']['primary'], 'retrieval_failure')
        self.assertEqual(t['tools'][0]['error']['code'], 'tool_execution_error')
        self.assertNotIn('private retrieval detail', serialize(t))

    def test_tool_failure(self):
        class BrokenData:
            def lookup(self, *args):
                raise RuntimeError('private data')
        t = run(data=BrokenData(), provider=Provider(abstention()))
        self.assertEqual(t['failure_attribution']['primary'], 'tool_failure')
        self.assertEqual(t['tools'][0]['status'], 'error')

    def test_routing_failure(self):
        t = run(labels={'expected_tools': ['document_retrieval']})
        self.assertEqual(t['failure_attribution']['primary'], 'routing_failure')
        with patch('src.agentic.orchestrator.Orchestrator.route', side_effect=ValueError('PII')):
            p = Provider()
            t = run(provider=p)
            self.assertEqual(p.calls, 0)
            self.assertEqual(t['failure_attribution']['primary'], 'routing_failure')

    def test_generation_failure(self):
        t = run(provider=Provider(fail=True))
        self.assertEqual(t['failure_attribution']['primary'], 'generation_failure')
        self.assertEqual(t['lower_level']['error']['code'], 'timeout')
        self.assertIsNone(t['generation']['token_usage']['total_tokens'])
        self.assertIsNone(t['abstention']['observed'])

    def test_citation_failure(self):
        raw = json.dumps({'answer': 'Revenue 100 [C999].', 'citations': ['C999'], 'abstained': False})
        t = run(provider=Provider(raw))
        self.assertTrue(t['validation']['json_schema_valid'])
        self.assertFalse(t['validation']['citation_valid'])
        self.assertIn('citation_failure', t['failure_attribution']['categories'])
        self.assertIn('invalid_output', t['failure_attribution']['categories'])

    def test_invalid_output(self):
        t = run(provider=Provider('not JSON'))
        self.assertEqual(t['failure_attribution']['primary'], 'invalid_output')
        self.assertFalse(t['validation']['json_schema_valid'])
        self.assertIsNone(t['validation']['citation_valid'])

    def test_partial_evidence_does_not_hide_generation_error(self):
        t = run('What was Apple revenue in 2025 and why did it change?', retriever=Retriever(empty=True), provider=Provider('not JSON'))
        self.assertEqual(t['failure_attribution']['primary'], 'partial_evidence')
        self.assertIn('invalid_output', t['failure_attribution']['categories'])
        self.assertEqual(t['tools'][1]['status'], 'success')

    def test_latency_and_token_aggregation(self):
        rows=[]
        for i, elapsed in enumerate([1, 2, 3, 4, 100]):
            t=run(trace_id=str(i))
            t['latency']['end_to_end_seconds']=elapsed
            t['retrieval']['latency_seconds']=elapsed
            t['routing']['tools_selected']=['document_retrieval']
            t['generation']['latency_seconds']=elapsed / 2
            rows.append(t)
        a=aggregate(rows)
        self.assertEqual(a['latency_seconds']['end_to_end']['mean'], 22)
        self.assertEqual(a['latency_seconds']['end_to_end']['median'], 3)
        self.assertEqual(a['latency_seconds']['end_to_end']['p95'], 100)
        self.assertEqual(a['latency_seconds']['retrieval']['median'], 3)
        self.assertEqual(a['latency_seconds']['generation']['median'], 1.5)
        self.assertEqual(a['tokens']['total_tokens']['total'], 150)
        self.assertEqual(a['tokens']['total_tokens']['average'], 30)
        self.assertEqual(a, aggregate(list(reversed(rows))))

    def test_missing_metrics_and_duplicate_handling(self):
        t=run()
        t['generation']['token_usage'] = dict.fromkeys(['input_tokens','output_tokens','total_tokens'])
        t['latency']['end_to_end_seconds']=None
        a=aggregate([t,t])
        self.assertEqual(a['total_queries'],1)
        self.assertIsNone(a['tokens']['total_tokens']['total'])
        self.assertIsNone(a['latency_seconds']['end_to_end']['mean'])
        self.assertIsNone(a['routing_success_rate']['value'])
        changed=deepcopy(t);changed['timestamp']='changed'
        with self.assertRaises(ValueError):aggregate([t,changed])
        self.assertIsNone(aggregate([])['abstention_rate']['value'])

    def test_redaction_and_privacy_default(self):
        secret='opaque-secret-123'
        query='Apple revenue 2025 Jane Doe at 12 Main Street jane@example.org SSN 123-45-6789 phone 312-555-0199 '+secret
        with patch.dict(os.environ, {'SEC_USER_AGENT': secret}):
            t=run(query, provider=Provider(json.dumps({'answer': query+' [C001]', 'citations':['C001'],'abstained':False})))
        encoded=serialize(t)
        for forbidden in ['Jane Doe','12 Main Street','jane@example.org','123-45-6789','312-555-0199',secret,'SEC_USER_AGENT','api_key_env']:
            self.assertNotIn(forbidden,encoded)
        p=Privacy([secret], {query:query})
        cleaned=p.query(query)['text']
        for forbidden in [secret,'jane@example.org','123-45-6789','312-555-0199']:self.assertNotIn(forbidden,cleaned)
        self.assertEqual(p.clean({'password':secret})['password'],'[REDACTED]')

    def test_deterministic_serialization_and_save(self):
        t=make_trace('fixture','sensitive name',config(), timestamp='2026-01-01T00:00:00Z')
        other=make_trace('fixture','sensitive name',dict(reversed(list(config().items()))), timestamp='2026-01-01T00:00:00Z')
        self.assertEqual(serialize(t),serialize(other))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.json'; save_trace(path,t)
            self.assertEqual(path.read_text(),serialize(t))
            self.assertEqual(json.loads(path.read_text()),t)

    def test_provenance_tampering_detected(self):
        from src.generation.grounding import build_context
        original=chunk();contexts=build_context([original]);contexts[0]['ticker']='changed'
        raw=Provider().raw
        v,_=inspect_output(raw,contexts,[original])
        self.assertFalse(v['citation_valid'])
        self.assertFalse(v['output_contract_valid'])

    def test_historical_import_is_offline_and_deterministic(self):
        with patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')):
            a=import_phase4b(ROOT);b=import_phase5(ROOT)
            self.assertEqual(len(a),20);self.assertEqual(len(b),4)
            self.assertEqual(a,import_phase4b(ROOT))
        self.assertTrue(all(t['timestamp'] is None for t in a+b))
        self.assertTrue(all(t['routing']['correct'] is None for t in a))
        both=next(t for t in b if t['query']['id']=='P5-BOTH-001')
        self.assertIn('partial_evidence',both['failure_attribution']['categories'])
        self.assertIn('citation_failure',both['failure_attribution']['categories'])
        self.assertIsNone(both['retrieval']['latency_seconds'])
        self.assertEqual(aggregate(a)['tokens']['total_tokens']['total'],93522)


class ObservabilityAdditionalTests(unittest.TestCase):
    def test_cli_idempotence_and_saved_trace_aggregation(self):
        historical = json.loads((ROOT / 'evals/observability/phase6/protected_before.json').read_text())
        require_prepared_artifacts(ROOT, historical=historical)
        import contextlib
        import io
        from scripts.run_phase6_observability import main
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')):
            output=Path(directory)/'historical'
            self.assertEqual(main(['--output',str(output)]),0)
            integrity=json.loads((output/'protected_audit.json').read_text())
            self.assertEqual(integrity['verification_scope'],'current_repository_check')
            self.assertFalse(integrity['unchanged'])
            self.assertTrue(integrity['final_state_verified'])
            self.assertEqual(integrity['changed_files'],[])
            self.assertEqual(len(integrity['historical_differences']),1)
            difference=integrity['historical_differences'][0]
            self.assertEqual(difference['path'],'configs/dataset.json')
            self.assertEqual(difference['classification'],'one_trailing_newline_removed')
            self.assertTrue(difference['historical_hash_reconstructed'])
            self.assertTrue(difference['parsed_json_values_identical'])
            before={str(p.relative_to(output)):p.read_bytes() for p in output.rglob('*') if p.is_file()}
            self.assertEqual(main(['--output',str(output)]),0)
            self.assertEqual(before,{str(p.relative_to(output)):p.read_bytes() for p in output.rglob('*') if p.is_file()})
            second=Path(directory)/'reaggregated'
            self.assertEqual(main(['--trace-dir',str(output/'traces'),'--output',str(second)]),0)
            self.assertEqual(json.loads((output/'aggregate.json').read_text()),json.loads((second/'aggregate.json').read_text()))
            self.assertTrue((second/'report.md').exists())

    def test_partial_tokens_and_inconsistent_provider_total(self):
        from src.observability.trace import usage
        self.assertEqual(usage({'input_tokens':2,'output_tokens':3})['total_tokens'],5)
        self.assertIsNone(usage({'input_tokens':2,'output_tokens':3,'total_tokens':9})['total_tokens'])
        self.assertIsNone(usage({'input_tokens':True})['input_tokens'])
        first=run(trace_id='first');second=run(trace_id='second')
        second['generation']['token_usage']=usage(None)
        summary=aggregate([first,second])
        self.assertIsNone(summary['tokens']['total_tokens']['total'])
        self.assertEqual(summary['tokens']['total_tokens']['known_sum'],30)
        self.assertEqual(summary['tokens']['total_tokens']['unavailable'],1)

    def test_historical_adapter_time_not_retrieval(self):
        rows=import_phase5(ROOT)
        self.assertTrue(all(t['retrieval']['latency_seconds'] is None for t in rows))
        self.assertEqual(aggregate(import_phase4b(ROOT)+rows)['latency_seconds']['retrieval']['count'],20)
        both=next(t for t in rows if t['query']['id']=='P5-BOTH-001')
        self.assertEqual(both['lower_level']['error']['detail'],'Inline citations and citation list differ')

    def test_schema_validation(self):
        from src.observability.trace import validate_trace
        t=run()
        self.assertEqual(validate_trace(t),t)
        for key,value in [('schema_version','future'),('timestamp','2026-01-01')]:
            broken=deepcopy(t);broken[key]=value
            with self.assertRaises(ValueError):validate_trace(broken)
        broken=deepcopy(t);broken['failure_attribution']['primary']='invented'
        with self.assertRaises(ValueError):validate_trace(broken)

    def test_retry_token_accounting_never_uses_only_last_attempt(self):
        from src.observability.trace import generation_usage
        generation={'token_usage':{'input_tokens':2,'output_tokens':3},
                    'attempts':[{'usage':{'input_tokens':10,'output_tokens':5}},
                                {'usage':{'input_tokens':2,'output_tokens':3}}]}
        self.assertEqual(generation_usage(generation)['total_tokens'],20)
        generation['attempts'][0]['usage']=None
        self.assertIsNone(generation_usage(generation)['total_tokens'])


    def test_unsafe_trace_ids_and_invalid_tokens_rejected(self):
        t=run()
        for identity in ['../escape', '/absolute', '']:
            broken=deepcopy(t);broken['trace_id']=identity
            with self.assertRaises(ValueError):aggregate([broken])
        for value in [-1, True, 1.5]:
            broken=deepcopy(t);broken['generation']['token_usage']['input_tokens']=value
            with self.assertRaises(ValueError):aggregate([broken])


    def test_expected_abstention_accuracy(self):
        a=run('Explain business',provider=Provider(abstention()),labels={'expected_abstention':True})
        b=run(labels={'expected_abstention':True})
        c=run(labels={'expected_abstention':False})
        metrics=aggregate([a,b,c])
        self.assertEqual(metrics['expected_abstention_accuracy']['denominator'],2)
        self.assertEqual(metrics['expected_abstention_accuracy']['value'],0.5)
        self.assertEqual(metrics['abstention_label_accuracy']['value'],2/3)

    def test_full_context_count_keeps_combined_financial_fact(self):
        class Five:
            def retrieve(self,*args):
                return [dict(chunk(),chunk_id=str(i)) for i in range(5)]
        class ContextProvider(Provider):
            def generate(self,prompt,*args):
                self.evidence=json.loads(prompt['input'])['evidence']
                return super().generate(prompt,*args)
        p=ContextProvider(abstention())
        t=run('Apple revenue 2025 and why did it change?',retriever=Five(),provider=p)
        self.assertEqual(len(p.evidence),6)
        self.assertEqual(t['retrieval']['configuration']['top_k'],5)
        self.assertEqual(len(t['retrieval']['evidence']),5)


if __name__ == '__main__':
    unittest.main()
