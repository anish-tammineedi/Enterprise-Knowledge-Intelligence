from dataclasses import dataclass, field
import math
from typing import Protocol


@dataclass(frozen=True)
class Question:
    question_id: str
    text: str

    def __post_init__(self):
        if not isinstance(self.question_id, str) or not self.question_id.strip() or not isinstance(self.text, str) or not self.text.strip():
            raise ValueError('Question requires a nonempty identifier and text')


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    temperature: float = 0
    max_output_tokens: int = 1000
    timeout_seconds: float = 45
    max_retries: int = 2
    retry_delay_seconds: float = 1
    api_key_env: str = 'OPENAI_API_KEY'
    provider_options: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.provider_options, dict):
            raise ValueError('Provider options must be an object')
        if not self.provider or not self.model or not self.api_key_env.isidentifier():
            raise ValueError('Provider, model and credential environment name are required')
        for value in [self.temperature, self.timeout_seconds, self.retry_delay_seconds]:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Invalid numeric LLM configuration')
        if not 0 <= self.temperature <= 2 or self.timeout_seconds <= 0 or self.retry_delay_seconds < 0:
            raise ValueError('Invalid temperature, timeout or retry delay')
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0 or type(self.max_retries) is not int or not 0 <= self.max_retries <= 5:
            raise ValueError('Invalid token limit or retry count')


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    usage: dict | None = None
    response_id: str | None = None
    model: str | None = None
    finish_status: str = 'completed'
    metadata: dict | None = None


class ProviderError(Exception):
    def __init__(self, code, retryable=False, status_code=None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class LLMProvider(Protocol):
    def generate(self, prompt: dict, schema: dict, config: LLMConfig) -> ProviderResponse:
        ...


class Retriever(Protocol):
    def retrieve(self, question: str, mode: str, top_k: int) -> list[dict]:
        ...
