from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import time

from src.embeddings.local_dense import digest, write_json
from src.generation.contracts import LLMConfig, ProviderError
from src.generation.grounding import SCHEMA, build_context, build_prompt, canonical, validate_citation_grounding, validate_output


def prepare(question, retriever, config):
    llm = LLMConfig(**config['llm'])
    mode, top_k = config['retrieval']['mode'], config['retrieval']['top_k']
    if mode not in ['bm25', 'hybrid'] or type(top_k) is not int or top_k <= 0:
        raise ValueError('Invalid retrieval configuration')
    started = time.perf_counter()
    retrieved = retriever.retrieve(question.text, mode, top_k)
    retrieval_seconds = time.perf_counter() - started
    if len(retrieved) > top_k:
        raise ValueError('Retriever exceeded requested context depth')
    contexts = build_context(retrieved)
    prompt = build_prompt(question, contexts, config['prompt'])
    generation_config = {'llm': asdict(llm), 'retrieval': config['retrieval'], 'prompt': config['prompt']}
    return {'question_id': question.question_id, 'question': question.text, 'retrieval_mode': mode, 'top_k': top_k,
            'retrieved_context_ids': [c['context_id'] for c in contexts], 'contexts': contexts,
            'retrieval': [{'chunk_id': c['chunk_id'], 'rank': i, 'score': c.get('retrieval_score'),
                           'score_type': c.get('retrieval_score_type')} for i, c in enumerate(retrieved, 1)],
            'prompt': prompt, 'schema': SCHEMA, 'prompt_sha256': digest(prompt),
            'config_sha256': digest(generation_config), 'config': generation_config,
            'provider': llm.provider, 'model': llm.model, 'retrieval_latency_seconds': retrieval_seconds}, retrieved, llm


def redact_secrets(value, environment_name):
    text = canonical(value)
    key = os.environ.get(environment_name)
    if key:
        text = text.replace(json.dumps(key, ensure_ascii=False)[1:-1], '[REDACTED]')
    text = re.sub(r'sk-[A-Za-z0-9_-]{12,}', '[REDACTED]', text)
    return json.loads(text)


def save_trace(directory, trace):
    safe = redact_secrets(trace, trace['config']['llm']['api_key_env'])
    path = Path(directory) / (digest(safe) + '.json')
    write_json(path, safe)
    return path


def generate(question, retriever, provider, config, trace_directory, sleep=time.sleep):
    started = time.perf_counter()
    llm = LLMConfig(**config['llm'])
    try:
        trace, retrieved, llm = prepare(question, retriever, config)
    except Exception:
        generation_config = {'llm': asdict(llm), 'retrieval': config['retrieval'], 'prompt': config['prompt']}
        trace = {'question_id': question.question_id, 'question': question.text,
                 'retrieval_mode': config['retrieval']['mode'], 'top_k': config['retrieval']['top_k'],
                 'retrieved_context_ids': [], 'contexts': [], 'retrieval': [], 'prompt': None,
                 'schema': SCHEMA, 'prompt_sha256': None, 'config_sha256': digest(generation_config),
                 'config': generation_config, 'provider': llm.provider, 'model': llm.model,
                 'status': 'preparation_error', 'attempts': [], 'raw_model_output': None,
                 'parsed_answer': None, 'citations': [], 'abstained': None, 'citation_validation': [],
                 'token_usage': None, 'error': {'code': 'preparation_failed'},
                 'latency_seconds': time.perf_counter() - started, 'generation_latency_seconds': 0}
        path = save_trace(trace_directory, trace)
        return redact_secrets(trace, llm.api_key_env), path
    trace.update(status='pending', attempts=[], raw_model_output=None, parsed_answer=None,
                 citations=[], abstained=None, citation_validation=[], token_usage=None, error=None)
    for attempt in range(llm.max_retries + 1):
        attempt_start = time.perf_counter()
        entry = {'attempt': attempt + 1, 'raw_output': None, 'usage': None, 'error': None}
        retry = False
        try:
            response = provider.generate(deepcopy(trace['prompt']), deepcopy(SCHEMA), llm)
            entry.update(raw_output=response.text, usage=response.usage, response_id=response.response_id,
                         response_model=response.model, finish_status=response.finish_status,
                         provider_metadata=response.metadata)
            trace['raw_model_output'], trace['token_usage'] = response.text, response.usage
            if response.finish_status != 'completed':
                entry['error'] = {'code': 'provider_' + response.finish_status}
                trace['status'] = 'provider_error'
            else:
                try:
                    parsed = validate_output(response.text, trace['contexts'])
                    grounding = validate_citation_grounding(parsed, trace['contexts'], retrieved)
                    trace.update(status='success', parsed_answer=parsed, citations=parsed['citations'],
                                 abstained=parsed['abstained'], citation_validation=grounding)
                except ValueError as error:
                    entry['error'] = {'code': 'invalid_output', 'detail': str(error)}
                    trace['status'] = 'invalid_output'
        except ProviderError as error:
            entry['error'] = {'code': error.code, 'status_code': error.status_code, 'retryable': error.retryable}
            trace['status'] = 'provider_error'
            retry = error.retryable and attempt < llm.max_retries
        except Exception:
            entry['error'] = {'code': 'unexpected_provider_error'}
            trace['status'] = 'provider_error'
        entry['latency_seconds'] = time.perf_counter() - attempt_start
        trace['attempts'].append(entry)
        trace['error'] = entry['error']
        if not retry:
            break
        sleep(llm.retry_delay_seconds * 2 ** attempt)
    trace['latency_seconds'] = time.perf_counter() - started
    trace['generation_latency_seconds'] = sum(a['latency_seconds'] for a in trace['attempts'])
    path = save_trace(trace_directory, trace)
    return redact_secrets(trace, llm.api_key_env), path
