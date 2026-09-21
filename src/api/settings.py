from dataclasses import dataclass
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path
    host: str = '127.0.0.1'
    port: int = 8000
    retrieval_mode: str = 'bm25'
    retrieval_top_k: int = 5
    ollama_base_url: str = 'http://127.0.0.1:11434'
    ollama_model: str = 'qwen3:4b-instruct-2507-q4_K_M'
    provider: str = 'ollama'
    request_timeout_seconds: float = 120
    trace_dir: Path | None = None
    max_concurrency: int = 4

    @classmethod
    def from_env(cls, root=None, environ=None):
        env = os.environ if environ is None else environ
        root = Path(root or Path(__file__).resolve().parents[2]).resolve()
        generation = json.loads((root / 'configs/generation_ollama.json').read_text())
        retrieval = generation['retrieval']
        settings = cls(
            root=root,
            host=env.get('EKI_HOST', '127.0.0.1'),
            port=_integer(env.get('EKI_PORT', '8000'), 'EKI_PORT', 1, 65535),
            retrieval_mode=env.get('EKI_RETRIEVAL_MODE', retrieval['mode']),
            retrieval_top_k=_integer(env.get('EKI_RETRIEVAL_TOP_K', str(retrieval['top_k'])), 'EKI_RETRIEVAL_TOP_K', 1, 100),
            ollama_base_url=env.get('EKI_OLLAMA_BASE_URL', generation['llm']['provider_options']['base_url']),
            ollama_model=env.get('EKI_OLLAMA_MODEL', generation['llm']['model']),
            provider=env.get('EKI_PROVIDER', generation['llm']['provider']),
            request_timeout_seconds=_positive_float(env.get('EKI_REQUEST_TIMEOUT_SECONDS', '120'), 'EKI_REQUEST_TIMEOUT_SECONDS'),
            trace_dir=Path(env['EKI_TRACE_DIR']).expanduser().resolve() if env.get('EKI_TRACE_DIR') else root / 'data/processed/service_traces',
            max_concurrency=_integer(env.get('EKI_MAX_CONCURRENCY', '4'), 'EKI_MAX_CONCURRENCY', 1, 32),
        )
        if settings.retrieval_mode not in ('bm25', 'hybrid'):
            raise ValueError('EKI_RETRIEVAL_MODE must be bm25 or hybrid')
        if settings.provider != 'ollama':
            raise ValueError('EKI_PROVIDER must be ollama for this local service')
        return settings

    def generation_config(self):
        value = json.loads((self.root / 'configs/generation_ollama.json').read_text())
        value['retrieval']['mode'] = self.retrieval_mode
        value['retrieval']['top_k'] = self.retrieval_top_k
        value['llm']['model'] = self.ollama_model
        value['llm']['timeout_seconds'] = min(value['llm']['timeout_seconds'], self.request_timeout_seconds)
        value['llm']['provider_options']['base_url'] = self.ollama_base_url
        value['llm']['max_retries'] = 0
        value['llm']['max_output_tokens'] = min(value['llm']['max_output_tokens'], 1000)
        return value


def _integer(value, name, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(name + ' must be an integer') from None
    if str(number) != str(value).strip() or not low <= number <= high:
        raise ValueError(name + ' is outside its allowed range')
    return number


def _positive_float(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(name + ' must be numeric') from None
    if not 0 < number <= 3600:
        raise ValueError(name + ' is outside its allowed range')
    return number
