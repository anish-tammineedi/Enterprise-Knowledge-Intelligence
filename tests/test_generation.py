from contextlib import redirect_stdout
from copy import deepcopy
import io
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.run_grounded_generation import main, sample_questions
from src.generation.contracts import LLMConfig, ProviderError, ProviderResponse, Question
from src.generation.grounding import ABSTENTION, SCHEMA, build_context, build_prompt, canonical, validate_citation_grounding, validate_output
from src.generation.pipeline import generate, prepare, save_trace
from src.generation.providers import OpenAIProvider, create_provider
from src.generation.retrieval import SECSectionRetriever, verify_protected


ROOT = Path(__file__).resolve().parents[1]


def chunk():
    text = 'The company reported revenue of $100 million.'
    return {'chunk_id': 'chunk-a', 'document_id': 'doc-a', 'source_document_id': 'doc-a',
            'company': 'Example', 'ticker': 'EX', 'cik': '1', 'form': '10-K', 'filing_date': '2025-10-31',
            'report_date': '2025-09-30', 'accession_number': 'acc-a', 'item': '7', 'section_id': 'doc-a:7',
            'section_name': 'MD&A', 'sections': [{'section_id': 'doc-a:7'}],
            'source_url': 'https://www.sec.gov/example', 'start_char': 0, 'end_char': len(text), 'text': text}


class FakeRetriever:
    def retrieve(self, question, mode, top_k):
        return [chunk()]


class FakeProvider:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def generate(self, prompt, schema, config):
        self.calls.append((deepcopy(prompt), deepcopy(schema), config))
        result = next(self.outputs)
        if isinstance(result, Exception):
            raise result
        return result


def config():
    c = json.loads((ROOT / 'configs/generation.json').read_text())
    c['llm']['retry_delay_seconds'] = 0
    return c


def success():
    return ProviderResponse(json.dumps({'answer': 'Revenue was $100 million [C001].', 'citations': ['C001'], 'abstained': False}),
                            {'input_tokens': 20, 'output_tokens': 10, 'total_tokens': 30}, 'response-test', 'fake-model')


class GenerationTests(unittest.TestCase):
    def test_deterministic_prompt_and_provenance(self):
        c = chunk()
        c['expected_answer'] = 'MUST_NOT_LEAK'
        contexts = build_context([c])
        self.assertEqual(contexts[0]['chunk_id'], c['chunk_id'])
        for key in ['company', 'ticker', 'accession_number', 'item', 'section_name', 'source_url', 'text']:
            self.assertEqual(contexts[0][key], c[key])
        self.assertEqual(contexts[0]['report_year'], 2025)
        q = Question('Q', 'What was revenue?')
        a = build_prompt(q, contexts, config()['prompt'])
        b = build_prompt(q, build_context([dict(reversed(list(c.items())))]), config()['prompt'])
        self.assertEqual(canonical(a).encode(), canonical(b).encode())
        self.assertNotIn('MUST_NOT_LEAK', canonical(a))
        self.assertIn('untrusted data', a['instructions'])
        with self.assertRaises(ValueError):
            build_context([c, c])
        with self.assertRaises(ValueError):
            build_prompt(q, contexts, {'version': 'sec_grounded_v1', 'max_context_characters': 1})

    def test_output_schema_and_abstention(self):
        contexts = build_context([chunk()])
        value = validate_output(success().text, contexts)
        self.assertFalse(value['abstained'])
        abstention = {'answer': ABSTENTION, 'citations': [], 'abstained': True}
        self.assertTrue(validate_output(json.dumps(abstention), contexts)['abstained'])
        self.assertTrue(validate_output(json.dumps(abstention), [])['abstained'])
        cases = ['not json', '```json\n{}\n```', '[]', '{"answer":"one","answer":"two"}',
                 json.dumps({**value, 'answer': ''}), json.dumps({**value, 'citations': ['C999']}),
                 json.dumps({**value, 'answer': 'A claim [C999].'}), json.dumps({**value, 'answer': 'A claim [Cfake].'}),
                 json.dumps({**value, 'citations': ['C001', 'C001']}), json.dumps({**value, 'abstained': 'false'}),
                 json.dumps({**value, 'abstained': True}), json.dumps({**value, 'extra': 1}),
                 json.dumps({'answer': ABSTENTION, 'citations': [], 'abstained': False}),
                 json.dumps({'answer': 'A claim.', 'citations': [], 'abstained': False})]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_output(raw, contexts)

    def test_citation_retrieval_membership_and_tampering(self):
        original = chunk()
        contexts = build_context([original])
        output = validate_output(success().text, contexts)
        refs = validate_citation_grounding(output, contexts, [original])
        self.assertEqual(refs[0]['chunk_id'], 'chunk-a')
        for field in ['text', 'ticker', 'source_url', 'accession_number', 'chunk_id']:
            altered = deepcopy(contexts)
            altered[0][field] = 'tampered'
            with self.assertRaises(ValueError):
                validate_citation_grounding(output, altered, [original])
        with self.assertRaises(ValueError):
            validate_citation_grounding(output, contexts, [])

    def test_trace_serialization_and_no_credentials_required(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            provider = FakeProvider([success()])
            trace, path = generate(Question('Q', 'What was revenue?'), FakeRetriever(), provider, config(), directory)
            loaded = json.loads(path.read_text())
            self.assertEqual(loaded, trace)
            self.assertEqual(trace['status'], 'success')
            self.assertEqual(trace['token_usage']['total_tokens'], 30)
            self.assertEqual(trace['retrieved_context_ids'], ['C001'])
            self.assertEqual(trace['raw_model_output'], success().text)
            self.assertGreaterEqual(trace['latency_seconds'], 0)
            self.assertEqual(save_trace(directory, trace), path)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(trace['citation_validation'][0]['source_url'], chunk()['source_url'])

    def test_retries_provider_failures_and_invalid_output(self):
        cases = [(FakeProvider([ProviderError('timeout', True), success()]), 'success', 2),
                 (FakeProvider([ProviderError('timeout', True)] * 3), 'provider_error', 3),
                 (FakeProvider([ProviderError('http_error', False, 401)]), 'provider_error', 1),
                 (FakeProvider([ProviderResponse('bad json')]), 'invalid_output', 1),
                 (FakeProvider([ProviderResponse('partial', finish_status='incomplete')]), 'provider_error', 1),
                 (FakeProvider([ProviderResponse('refused', finish_status='refused')]), 'provider_error', 1),
                 (FakeProvider([RuntimeError('sensitive error')]), 'provider_error', 1)]
        for provider, status, attempts in cases:
            with tempfile.TemporaryDirectory() as directory:
                trace, _ = generate(Question('Q', 'Revenue?'), FakeRetriever(), provider, config(), directory, sleep=lambda seconds: None)
                self.assertEqual(trace['status'], status)
                self.assertEqual(len(trace['attempts']), attempts)
                if status != 'success':
                    self.assertIsNone(trace['abstained'])
                    self.assertIsNone(trace['parsed_answer'])
                    self.assertIsNotNone(trace['error'])
                    self.assertNotIn('sensitive error', canonical(trace))

    def test_secret_redaction(self):
        key = 'sk-secret-value-for-unit-test'
        response = ProviderResponse(json.dumps({'answer': key + ' [C001]', 'citations': ['C001'], 'abstained': False}))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'OPENAI_API_KEY': key}):
            trace, path = generate(Question('Q', 'Revenue?'), FakeRetriever(), FakeProvider([response]), config(), directory)
            self.assertNotIn(key, path.read_text())
            self.assertNotIn(key, canonical(trace))

    def test_openai_backend_request_and_response(self):
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {'id': 'r1', 'model': 'test', 'status': 'completed',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': success().text}]}],
            'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}):
            response = OpenAIProvider(session).generate({'instructions': 'rules', 'input': 'data'}, SCHEMA, LLMConfig(**config()['llm']))
        self.assertEqual(response.text, success().text)
        request = session.post.call_args.kwargs
        self.assertEqual(request['timeout'], 45)
        self.assertFalse(request['allow_redirects'])
        self.assertFalse(request['json']['store'])
        self.assertEqual(request['json']['text']['format']['schema'], SCHEMA)
        self.assertEqual(request['json']['max_output_tokens'], 1000)
        self.assertEqual(response.usage['total_tokens'], 15)

    def test_openai_errors_without_live_requests(self):
        session = Mock()
        backend = OpenAIProvider(session)
        llm = LLMConfig(**config()['llm'])
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ProviderError) as error:
            backend.generate({}, SCHEMA, llm)
        self.assertEqual(error.exception.code, 'missing_api_key')
        session.post.assert_not_called()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-key'}):
            for failure, code in [(requests.Timeout(), 'timeout'), (requests.ConnectionError(), 'transport_error')]:
                session.post.side_effect = failure
                with self.assertRaises(ProviderError) as error:
                    backend.generate({'instructions': '', 'input': ''}, SCHEMA, llm)
                self.assertEqual(error.exception.code, code)
                self.assertTrue(error.exception.retryable)
            session.post.side_effect = None
            for status, retryable in [(429, True), (503, True), (401, False), (302, False)]:
                session.post.return_value.status_code = status
                with self.assertRaises(ProviderError) as error:
                    backend.generate({'instructions': '', 'input': ''}, SCHEMA, llm)
                self.assertEqual(error.exception.retryable, retryable)
            session.post.return_value.status_code = 200
            session.post.return_value.json.side_effect = ValueError()
            with self.assertRaises(ProviderError):
                backend.generate({'instructions': '', 'input': ''}, SCHEMA, llm)
        with self.assertRaises(ValueError):
            create_provider('unknown')

    def test_benchmark_answers_do_not_reach_generation(self):
        benchmark = json.loads((ROOT / 'evals/ground_truth/sec_retrieval_benchmark.json').read_text())
        original = sample_questions(benchmark)
        changed = deepcopy(benchmark)
        for row in changed['questions']:
            for key in ['expected_answer', 'evidence', 'required_documents', 'answerable', 'difficulty']:
                row[key] = 'GOLD_SENTINEL_NEVER_SEND'
        altered = sample_questions(changed)
        self.assertEqual(original, altered)
        for q in altered:
            trace, _, _ = prepare(q, FakeRetriever(), config())
            self.assertNotIn('GOLD_SENTINEL', canonical(trace['prompt']))
            self.assertEqual(set(json.loads(trace['prompt']['input'])), {'question', 'evidence'})

    def test_real_retrieval_and_protected_immutability(self):
        manifest = json.loads((ROOT / 'configs/generation_protected.json').read_text())
        if not all((ROOT / path).is_file() for path in manifest['sha256']):
            self.skipTest('Protected SEC corpus artifacts are not prepared')
        verify_protected(ROOT, manifest)
        c = config()
        retriever = SECSectionRetriever(ROOT, c['retrieval'])
        benchmark = json.loads((ROOT / 'evals/ground_truth/sec_retrieval_benchmark.json').read_text())
        questions = sample_questions(benchmark)
        for mode in ['bm25', 'hybrid']:
            prior = {r['question_id']: r for kind in ['answerable', 'unanswerable']
                     for r in json.loads((ROOT / 'evals/results/lexical_hybrid/7bc596de695ce349/sec_section' / mode / (kind + '_results.json')).read_text())}
            for q in questions:
                for k in [5, 10]:
                    found = retriever.retrieve(q.text, mode, k)
                    self.assertEqual([r['chunk_id'] for r in found], [r['chunk_id'] for r in prior[q.question_id]['results'][:k]])
                    self.assertEqual(len(found), k)
                    self.assertEqual(found[0]['text'], prior[q.question_id]['results'][0]['text'])
        verify_protected(ROOT, manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'frozen').mkdir()
            (root / 'frozen/a').write_text('before')
            m = {'roots': ['frozen'], 'sha256': {'frozen/a': hashlib.sha256(b'before').hexdigest()}}
            verify_protected(root, m)
            (root / 'frozen/a').write_text('after')
            with self.assertRaises(ValueError):
                verify_protected(root, m)

    def test_preparation_failure_is_traced_without_provider_call(self):
        retriever = Mock()
        retriever.retrieve.side_effect = RuntimeError('sensitive error')
        provider = FakeProvider([])
        with tempfile.TemporaryDirectory() as directory:
            trace, path = generate(Question('Q', 'Revenue?'), retriever, provider, config(), directory)
            self.assertEqual(trace['status'], 'preparation_error')
            self.assertIsNone(trace['abstained'])
            self.assertIsNone(trace['prompt_sha256'])
            self.assertEqual(provider.calls, [])
            self.assertTrue(path.exists())
            self.assertNotIn('sensitive error', path.read_text())

    def test_default_cli_offline_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            c = config()
            c['output_dir'] = str(Path(directory) / 'outputs')
            config_path = Path(directory) / 'config.json'
            config_path.write_text(json.dumps(c))
            with patch('scripts.run_grounded_generation.create_provider', side_effect=AssertionError('No provider allowed')):
                self.assertEqual(main(['--config', str(config_path)]), 0)
                files = list((Path(directory) / 'outputs/prepared').glob('*.json'))
                self.assertEqual(len(files), 4)
                before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}
                self.assertEqual(main(['--config', str(config_path)]), 0)
                self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files})
                for p in files:
                    self.assertEqual(json.loads(p.read_text())['status'], 'prepared_only_no_model_call')

    def test_config_and_context_limits(self):
        for override in [{'max_retries': 6}, {'max_output_tokens': 0}, {'temperature': float('nan')}, {'timeout_seconds': 0}]:
            with self.assertRaises(ValueError):
                LLMConfig(**{**config()['llm'], **override})
        with self.assertRaises(ValueError):
            Question('', 'text')
        c = config()
        c['retrieval']['top_k'] = 0
        with self.assertRaises(ValueError):
            prepare(Question('Q', 'text'), FakeRetriever(), c)


if __name__ == '__main__':
    unittest.main()
