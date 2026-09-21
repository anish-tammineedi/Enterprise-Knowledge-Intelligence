import ipaddress
import re
from urllib.parse import urlparse

import requests

from src.generation.contracts import ProviderError, ProviderResponse


def local_endpoint(url):
    parsed = urlparse(url)
    try:
        local = parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname).is_loopback
    except (ValueError, TypeError):
        local = False
    if parsed.scheme != 'http' or not local or parsed.username or parsed.password or parsed.path not in ['', '/'] or parsed.query or parsed.fragment:
        raise ValueError('Ollama endpoint must be a credential-free loopback HTTP address')
    return url.rstrip('/')


class OllamaProvider:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.trust_env = False

    def _request(self, method, endpoint, config, payload=None):
        try:
            response = self.session.request(method, endpoint, json=payload, timeout=config.timeout_seconds, allow_redirects=False)
        except requests.Timeout:
            raise ProviderError('timeout', retryable=True) from None
        except requests.RequestException:
            raise ProviderError('transport_error', retryable=True) from None
        if response.status_code != 200:
            raise ProviderError('ollama_http_error', retryable=response.status_code in [408, 429] or response.status_code >= 500,
                                status_code=response.status_code)
        try:
            body = response.json()
            if not isinstance(body, dict) or 'error' in body:
                raise ValueError()
            return body
        except (ValueError, TypeError):
            raise ProviderError('invalid_provider_response') from None

    def generate(self, prompt, schema, config):
        options = config.provider_options
        allowed = {'base_url', 'num_ctx', 'seed', 'keep_alive', 'model_digest'}
        if set(options) - allowed:
            raise ValueError('Unsupported Ollama options')
        endpoint = local_endpoint(options.get('base_url', 'http://127.0.0.1:11434'))
        context = options.get('num_ctx', 16384)
        seed = options.get('seed', 0)
        if type(context) is not int or context < 2048 or type(seed) is not int:
            raise ValueError('Invalid Ollama context or seed')
        expected = options.get('model_digest')
        if expected is not None and not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Model digest must be a full SHA-256')
        tags = self._request('GET', endpoint + '/api/tags', config)
        try:
            installed = next(m for m in tags['models'] if m.get('name') == config.model or m.get('model') == config.model)
            if installed.get('remote_host') or installed.get('remote_model') or config.model.endswith('-cloud') or config.model.endswith(':cloud'):
                raise ProviderError('remote_model_not_allowed')
            model_digest = installed['digest']
            if not re.fullmatch(r'[0-9a-f]{64}', model_digest):
                raise ValueError()
        except StopIteration:
            raise ProviderError('local_model_not_installed') from None
        except (KeyError, TypeError, ValueError):
            raise ProviderError('invalid_model_metadata') from None
        if expected is not None and model_digest != expected:
            raise ProviderError('model_digest_mismatch')
        version = self._request('GET', endpoint + '/api/version', config).get('version')
        payload = {'model': config.model, 'stream': False, 'think': False, 'format': schema,
                   'messages': [{'role': 'system', 'content': prompt['instructions']}, {'role': 'user', 'content': prompt['input']}],
                   'options': {'temperature': config.temperature, 'num_predict': config.max_output_tokens,
                               'num_ctx': context, 'seed': seed}, 'keep_alive': options.get('keep_alive', '5m')}
        body = self._request('POST', endpoint + '/api/chat', config, payload)
        try:
            text = body['message']['content']
            if not isinstance(text, str) or body.get('model') != config.model:
                raise ValueError()
            done_reason = body.get('done_reason')
            finish = 'completed' if body.get('done') is True and done_reason == 'stop' else 'incomplete'
            usage = {}
            for source, target in [('prompt_eval_count', 'input_tokens'), ('eval_count', 'output_tokens')]:
                count = body.get(source)
                if type(count) is int and count >= 0:
                    usage[target] = count
            if len(usage) == 2:
                usage['total_tokens'] = sum(usage.values())
            timing = {key: body[key] for key in ['total_duration', 'load_duration', 'prompt_eval_duration', 'eval_duration']
                      if type(body.get(key)) is int and body[key] >= 0}
            metadata = {'model_digest': model_digest, 'ollama_version': version, 'endpoint': endpoint,
                        'generation_options': payload['options'], 'think': False, 'done_reason': done_reason,
                        'server_timings_nanoseconds': timing}
            return ProviderResponse(text, usage or None, model=config.model, finish_status=finish, metadata=metadata)
        except (ValueError, TypeError, KeyError):
            raise ProviderError('invalid_provider_response') from None
