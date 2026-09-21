import os

import requests

from src.generation.contracts import ProviderError, ProviderResponse


class OpenAIProvider:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def generate(self, prompt, schema, config):
        key = os.environ.get(config.api_key_env)
        if not key:
            raise ProviderError('missing_api_key')
        payload = {'model': config.model, 'temperature': config.temperature,
                   'max_output_tokens': config.max_output_tokens, 'store': False,
                   'instructions': prompt['instructions'], 'input': prompt['input'],
                   'text': {'format': {'type': 'json_schema', 'name': 'grounded_sec_answer', 'strict': True, 'schema': schema}}}
        try:
            response = self.session.post('https://api.openai.com/v1/responses',
                                         headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                                         json=payload, timeout=config.timeout_seconds, allow_redirects=False)
        except requests.Timeout:
            raise ProviderError('timeout', retryable=True) from None
        except requests.RequestException:
            raise ProviderError('transport_error', retryable=True) from None
        if response.status_code != 200:
            raise ProviderError('http_error', retryable=response.status_code in [408, 429] or response.status_code >= 500,
                                status_code=response.status_code)
        try:
            body = response.json()
            status = body.get('status', 'unknown')
            contents = [content for item in body.get('output', []) if item.get('type') == 'message' for content in item.get('content', [])]
            if any(c.get('type') == 'refusal' for c in contents):
                status = 'refused'
            text = ''.join(c.get('text', '') if c.get('type') == 'output_text' else c.get('refusal', '') for c in contents if c.get('type') in ['output_text', 'refusal'])
            if not isinstance(text, str):
                raise ValueError()
            usage = body.get('usage')
            safe_usage = {k: usage[k] for k in ['input_tokens', 'output_tokens', 'total_tokens']
                          if type(usage.get(k)) is int and usage[k] >= 0} if isinstance(usage, dict) else None
            return ProviderResponse(text, safe_usage, body.get('id'), body.get('model'), status)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderError('invalid_provider_response') from None


def create_provider(name):
    if name == 'ollama':
        from src.generation.ollama import OllamaProvider
        return OllamaProvider()
    if name == 'openai':
        return OpenAIProvider()
    raise ValueError('Unsupported provider; implement LLMProvider and register its adapter')
