from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from src.generation.contracts import LLMConfig, ProviderError
from src.generation.grounding import ABSTENTION, SCHEMA
from src.generation.ollama import OllamaProvider, local_endpoint
from src.generation.pipeline import generate
from src.generation.providers import create_provider
from src.generation.contracts import Question


MODEL = 'qwen3:4b-instruct-2507-q4_K_M'
DIGEST = 'a' * 64


def llm_config():
    return LLMConfig(provider='ollama', model=MODEL, timeout_seconds=600, max_retries=0,
                     provider_options={'base_url': 'http://127.0.0.1:11434', 'num_ctx': 16384, 'seed': 0, 'model_digest': DIGEST})


def response(body, status=200):
    result = Mock()
    result.status_code = status
    result.json.return_value = body
    return result


def responses(output=None, reason='stop'):
    raw = json.dumps(output or {'answer': ABSTENTION, 'citations': [], 'abstained': True})
    return [response({'models': [{'name': MODEL, 'digest': DIGEST}]}), response({'version': '0.34.1'}),
            response({'model': MODEL, 'message': {'content': raw}, 'done': True, 'done_reason': reason,
                      'prompt_eval_count': 123, 'eval_count': 20, 'total_duration': 2000000000,
                      'load_duration': 100000000, 'eval_duration': 500000000, 'prompt_eval_duration': 1400000000})]


class OllamaProviderTests(unittest.TestCase):
    def test_schema_options_usage_digest_and_no_api_key(self):
        session = Mock()
        session.request.side_effect = responses()
        with patch.dict(os.environ, {}, clear=True):
            result = OllamaProvider(session).generate({'instructions': 'rules', 'input': 'question'}, SCHEMA, llm_config())
        call = session.request.call_args
        self.assertEqual(call.args, ('POST', 'http://127.0.0.1:11434/api/chat'))
        payload = call.kwargs['json']
        self.assertEqual(payload['format'], SCHEMA)
        self.assertFalse(payload['stream'])
        self.assertFalse(payload['think'])
        self.assertEqual(payload['options']['num_ctx'], 16384)
        self.assertEqual(payload['options']['num_predict'], 1000)
        self.assertEqual(payload['options']['seed'], 0)
        self.assertEqual(payload['messages'][0], {'role': 'system', 'content': 'rules'})
        self.assertNotIn('Authorization', str(call))
        self.assertFalse(session.trust_env)
        self.assertFalse(call.kwargs['allow_redirects'])
        self.assertEqual(result.usage, {'input_tokens': 123, 'output_tokens': 20, 'total_tokens': 143})
        self.assertEqual(result.metadata['model_digest'], DIGEST)
        self.assertEqual(result.metadata['ollama_version'], '0.34.1')
        self.assertEqual(result.finish_status, 'completed')
        self.assertIsInstance(create_provider('ollama'), OllamaProvider)

    def test_loopback_only(self):
        for url in ['http://127.0.0.1:11434', 'http://localhost:11434/', 'http://[::1]:11434']:
            self.assertEqual(local_endpoint(url), url.rstrip('/'))
        for url in ['https://ollama.com', 'http://example.com', 'http://localhost.evil.test',
                    'http://user:password@localhost:11434', 'http://localhost/api', 'http://localhost?token=x']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                local_endpoint(url)

    def test_missing_changed_and_remote_models_never_generate(self):
        for models, code in [([], 'local_model_not_installed'),
                             ([{'name': MODEL, 'digest': 'b'*64}], 'model_digest_mismatch'),
                             ([{'name': MODEL, 'digest': DIGEST, 'remote_host': 'https://ollama.com'}], 'remote_model_not_allowed')]:
            session = Mock()
            session.request.return_value = response({'models': models})
            with self.assertRaises(ProviderError) as error:
                OllamaProvider(session).generate({}, SCHEMA, llm_config())
            self.assertEqual(error.exception.code, code)
            self.assertEqual(session.request.call_count, 1)

    def test_timeouts_errors_and_incomplete(self):
        for exception, code in [(requests.Timeout(), 'timeout'), (requests.ConnectionError(), 'transport_error')]:
            session = Mock()
            session.request.side_effect = exception
            with self.assertRaises(ProviderError) as error:
                OllamaProvider(session).generate({}, SCHEMA, llm_config())
            self.assertEqual(error.exception.code, code)
        for status, retryable in [(404, False), (429, True), (500, True), (302, False)]:
            session = Mock()
            session.request.return_value = response({}, status)
            with self.assertRaises(ProviderError) as error:
                OllamaProvider(session).generate({}, SCHEMA, llm_config())
            self.assertEqual(error.exception.retryable, retryable)
        session = Mock()
        session.request.side_effect = responses(reason='length')
        result = OllamaProvider(session).generate({'instructions': '', 'input': ''}, SCHEMA, llm_config())
        self.assertEqual(result.finish_status, 'incomplete')
        self.assertTrue(result.text)
        session = Mock()
        session.request.return_value = response({'error': 'sensitive upstream message'})
        with self.assertRaises(ProviderError) as error:
            OllamaProvider(session).generate({}, SCHEMA, llm_config())
        self.assertNotIn('sensitive', str(error.exception))

    def test_metadata_persists_in_provider_independent_trace(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root/'configs/generation.json').read_text())
        from dataclasses import asdict
        config['llm'] = asdict(llm_config())
        retriever = Mock()
        retriever.retrieve.return_value = []
        session = Mock()
        session.request.side_effect = responses()
        with tempfile.TemporaryDirectory() as directory:
            trace, path = generate(Question('sample', 'Unknown information?'), retriever, OllamaProvider(session), config, directory)
            self.assertEqual(trace['status'], 'success')
            self.assertTrue(trace['abstained'])
            self.assertEqual(trace['attempts'][0]['provider_metadata']['model_digest'], DIGEST)
            self.assertEqual(trace, json.loads(path.read_text()))


if __name__ == '__main__':
    unittest.main()
