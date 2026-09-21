import hashlib
import json
import math
import os
import re
from urllib.parse import urlsplit, urlunsplit

from src.generation.grounding import validate_output, validate_citation_grounding

TAXONOMY = ('success', 'expected_abstention', 'unsupported_query', 'retrieval_failure',
            'tool_failure', 'routing_failure', 'generation_failure', 'citation_failure',
            'invalid_output', 'partial_evidence')
PRIORITY = ('routing_failure', 'tool_failure', 'retrieval_failure', 'partial_evidence',
            'generation_failure', 'citation_failure', 'invalid_output', 'unsupported_query',
            'expected_abstention', 'success')
REDACTED = '[REDACTED]'
SAFE_ERROR_DETAILS = {
    'Malformed structured output', 'Unexpected structured output fields',
    'Answer and abstention types are invalid', 'Invalid or duplicate citations',
    'Citation references nonexistent context', 'Inline citations and citation list differ',
    'Abstention requires canonical answer and no citations',
    'Non-abstaining answer requires supporting citations',
    'Context text/provenance differs from retrieved chunks',
    'Citation was not retrieved for this question',
}


class Privacy:
    def __init__(self, secrets=(), reviewed_queries=None):
        self.secrets = tuple(sorted({s for s in secrets if isinstance(s, str) and s}, key=len, reverse=True))
        self.reviewed_queries = reviewed_queries or {}

    def clean(self, value):
        if isinstance(value, dict):
            sensitive = re.compile(r'(?i)(secret|password|authorization|user.agent|api.key|environment|prompt|raw.model|email|phone|ssn|personal|address|full.name|birth.date)')
            return {self.clean(str(k)): (REDACTED if sensitive.search(str(k)) else self.clean(v)) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, REDACTED)
            value = re.sub(r'(?i)\b(?:sk-|sk_)[a-z0-9_-]+', REDACTED, value)
            value = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', REDACTED, value)
            value = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', REDACTED, value)
            value = re.sub(r'(?<!\d)(?:\+1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)', REDACTED, value)
            return value
        return value

    def query(self, text):
        return {'text': self.clean(self.reviewed_queries[text]) if text in self.reviewed_queries else REDACTED,
                'policy': 'reviewed_public_text' if text in self.reviewed_queries else 'unreviewed_text_withheld'}


def privacy_from_config(config, reviewed_queries=None):
    names = ('SEC_USER_AGENT', config.get('llm', {}).get('api_key_env', 'OPENAI_API_KEY'))
    return Privacy([os.environ.get(name) for name in names], reviewed_queries)


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def usage(value):
    value = value or {}
    out = {k: value.get(k) if type(value.get(k)) is int and value[k] >= 0 else None
           for k in ('input_tokens', 'output_tokens', 'total_tokens')}
    if out['input_tokens'] is not None and out['output_tokens'] is not None:
        computed = out['input_tokens'] + out['output_tokens']
        if out['total_tokens'] is None:
            out['total_tokens'] = computed
        elif out['total_tokens'] != computed:
            out['total_tokens'] = None
    return out


def generation_usage(generation):
    attempts = generation.get('attempts') or []
    if len(attempts) <= 1:
        return usage(generation.get('token_usage'))
    rows = [usage(a.get('usage')) for a in attempts]
    return {key: sum(row[key] for row in rows) if all(row[key] is not None for row in rows) else None
            for key in ('input_tokens', 'output_tokens', 'total_tokens')}


def safe_config(config):
    llm = config.get('llm', {})
    options = llm.get('provider_options', {})
    return {'retrieval': {k: config.get('retrieval', {}).get(k) for k in ('mode', 'top_k')},
            'generation': {**{k: llm.get(k) for k in ('provider', 'model', 'temperature', 'max_output_tokens', 'timeout_seconds', 'max_retries')},
                           'provider_options': {k: options.get(k) for k in ('model_digest', 'num_ctx', 'seed')},
                           'prompt': {k: config.get('prompt', {}).get(k) for k in ('version', 'max_context_characters')}}}


def evidence_reference(row):
    keys = ('context_id', 'chunk_id', 'document_id', 'source_document_id', 'ticker', 'cik',
            'form', 'filing_date', 'report_date', 'accession_number', 'item', 'section_id',
            'start_char', 'end_char', 'metric', 'concept', 'unit', 'value', 'fiscal_year',
            'start', 'end', 'raw_fact_pointer', 'raw_sha256')
    ref = {k: row[k] for k in keys if k in row}
    url = row.get('source_url')
    if isinstance(url, str):
        parsed = urlsplit(url)
        if parsed.scheme == 'https' and parsed.hostname in ('www.sec.gov', 'data.sec.gov') and not parsed.username:
            ref['source_url'] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
    return ref


def safe_error(error):
    if not isinstance(error, dict):
        return None
    return {k: (REDACTED if k == 'detail' and (not isinstance(error[k], str) or error[k] not in SAFE_ERROR_DETAILS) else error[k]) for k in ('code', 'status_code', 'retryable', 'detail') if k in error}


def inspect_output(raw, contexts, retrieved=None):
    result = {'json_schema_valid': None, 'output_contract_valid': None, 'citation_valid': None,
              'errors': [], 'details': [], 'latency_seconds': None}
    observed = None
    if raw is None:
        return result, observed
    try:
        def unique(pairs):
            out = {}
            for k, v in pairs:
                if k in out:
                    raise ValueError('duplicate')
                out[k] = v
            return out
        parsed = json.loads(raw, object_pairs_hook=unique)
        schema_ok = (isinstance(parsed, dict) and set(parsed) == {'answer', 'citations', 'abstained'}
                     and isinstance(parsed['answer'], str) and bool(parsed['answer'].strip())
                     and type(parsed['abstained']) is bool and isinstance(parsed['citations'], list)
                     and all(isinstance(c, str) for c in parsed['citations']))
        result['json_schema_valid'] = schema_ok
        if not schema_ok:
            raise ValueError('schema')
        observed = parsed['abstained']
    except (TypeError, ValueError):
        result.update(json_schema_valid=False, output_contract_valid=False, errors=['invalid_output'], details=['Malformed structured output' if 'schema_ok' not in locals() else 'Unexpected structured output fields'])
        return result, observed
    allowed = {c.get('context_id') for c in contexts}
    citations = parsed['citations']
    result['citation_valid'] = (len(citations) == len(set(citations)) and set(citations) <= allowed
        and set(re.findall(r'\[(C[A-Za-z0-9_-]+)\]', parsed['answer'])) == set(citations)
        and (bool(citations) if not observed else not citations))
    try:
        validated = validate_output(raw, contexts)
        validate_citation_grounding(validated, contexts, contexts if retrieved is None else retrieved)
        result['output_contract_valid'] = True
    except ValueError as error:
        result['details'].append(str(error) if str(error) in SAFE_ERROR_DETAILS else REDACTED)
        result['output_contract_valid'] = False
        result['errors'].append('invalid_output')
        if result['citation_valid']:
            # Distinguish context provenance failure from an abstention-contract failure.
            try:
                validate_citation_grounding(parsed, contexts, contexts if retrieved is None else retrieved)
            except ValueError:
                result['citation_valid'] = False
    if result['citation_valid'] is False:
        result['errors'].append('citation_failure')
    return result, observed


def classify(trace):
    found = set(trace['validation']['errors'])
    routing = trace['routing']
    if routing['correct'] is False:
        found.add('routing_failure')
    if trace['lower_level'].get('routing_error'):
        found.add('routing_failure')
    for tool in trace['tools']:
        if tool['status'] in ('error', 'invalid_input'):
            found.add('retrieval_failure' if tool['name'] == 'document_retrieval' else 'tool_failure')
    if trace['generation']['status'] in ('provider_error', 'incomplete_output', 'generation_error'):
        found.add('generation_failure')
    if trace['generation']['status'] in ('preparation_error', 'invalid_output'):
        found.add('invalid_output')
    sufficient = trace['retrieval']['evidence_sufficient']
    financial_ok = any(t['name'] == 'financial_data' and t['status'] == 'success' for t in trace['tools'])
    if ('document_retrieval' in (routing['tools_selected'] or []) or trace['source']['kind'] == 'phase4b') and sufficient is False:
        found.add('partial_evidence' if financial_ok else 'retrieval_failure')
    if trace['result']['evidence_sufficient'] is False and financial_ok and len(trace['tools']) > 1:
        found.add('partial_evidence')
    if any(t['status'] == 'unavailable' for t in trace['tools']) and any(t['status'] == 'success' for t in trace['tools']):
        found.add('partial_evidence')
    if trace['abstention']['expected'] is True and trace['abstention']['observed'] is False:
        found.add('generation_failure')
    if trace['abstention']['expected'] is False and trace['abstention']['observed'] is True and trace['result']['evidence_sufficient'] is True:
        found.add('generation_failure')
    if routing['decision'] == 'abstain':
        found.add('unsupported_query')
    if trace['abstention']['expected'] is True and trace['abstention']['observed'] is True and trace['validation']['output_contract_valid'] is True:
        found.add('expected_abstention')
    if not found and trace['validation']['output_contract_valid'] is True:
        found.add('success')
    trace['failure_attribution'] = {'primary': next((k for k in PRIORITY if k in found), None),
                                    'categories': [k for k in TAXONOMY if k in found]}
    trace['result']['orchestration_status'] = trace['failure_attribution']['primary'] or 'unavailable'
    return trace


def make_trace(source, query, config, orchestration=None, generation=None, labels=None,
               timestamp=None, trace_id=None, privacy=None, source_kind='runtime'):
    privacy = privacy or Privacy()
    labels = labels or {}
    generation = generation or {}
    orchestration = orchestration or {}
    contexts = generation.get('contexts') or []
    checks, abstained = inspect_output(generation.get('raw_model_output'), contexts)
    selected = orchestration.get('selected_tools')
    tools = [{'name': t['tool_name'], 'status': t['status'], 'latency_seconds': number(t.get('latency_seconds')),
              'error': safe_error(t.get('error')), 'evidence': [evidence_reference(e) for e in t.get('evidence', [])]}
             for t in orchestration.get('tool_results', [])]
    safe = safe_config(config)
    expected_route = labels.get('expected_tools')
    observed_expected = labels.get('expected_abstention')
    out = {'schema_version': '6.1', 'trace_id': trace_id, 'timestamp': timestamp,
           'source': {'kind': source_kind, 'id': source}, 'query': {**privacy.query(query), 'id': trace_id},
           'routing': {'decision': '+'.join(selected) if selected else ('abstain' if selected == [] else None),
                       'reason': orchestration.get('routing_reason'), 'tools_selected': selected,
                       'correct': selected == expected_route if expected_route is not None and selected is not None else None,
                       'latency_seconds': None},
           'tools': tools,
           'retrieval': {'configuration': safe['retrieval'], 'evidence': [evidence_reference(c) for c in contexts if not c.get('chunk_id', '').startswith('financial:')],
                         'latency_seconds': number(generation.get('retrieval_latency_seconds')),
                         'latency_source': 'recorded_retrieval_stage' if generation.get('retrieval_latency_seconds') is not None else None,
                         'evidence_sufficient': labels.get('document_evidence_sufficient'),
                         'sufficiency_basis': labels.get('sufficiency_basis')},
           'generation': {'configuration': safe['generation'], 'status': generation.get('status'),
                          'latency_seconds': number(generation.get('generation_latency_seconds')),
                          'token_usage': generation_usage(generation)},
           'validation': checks,
           'abstention': {'observed': abstained, 'expected': observed_expected,
                          'correct': abstained == observed_expected if type(abstained) is bool and type(observed_expected) is bool else None},
           'result': {'orchestration_status': orchestration.get('status'),
                      'validation_status': 'passed' if checks['output_contract_valid'] is True else ('failed' if checks['output_contract_valid'] is False else 'unavailable'),
                      'evidence_sufficient': labels.get('evidence_sufficient'), 'claims_supported': labels.get('claims_supported'),
                      'answer': REDACTED if generation.get('raw_model_output') is not None else None,
                      'citations': generation.get('citations') or []},
           'latency': {'end_to_end_seconds': None, 'recorded_seconds': number(generation.get('latency_seconds')),
                       'recorded_scope': 'historical_generation_pipeline' if source_kind != 'runtime' else None,
                       'orchestration_seconds': number(orchestration.get('latency_seconds')),
                       'tool_seconds': sum(t['latency_seconds'] for t in tools) if tools and all(t['latency_seconds'] is not None for t in tools) else None},
           'lower_level': {'orchestration_status': orchestration.get('status'), 'generation_status': generation.get('status'),
                           'error': safe_error(generation.get('error')), 'legacy_attribution': labels.get('legacy_attribution'),
                           'attempts': [{'attempt': a.get('attempt'), 'error': safe_error(a.get('error')), 'token_usage': usage(a.get('usage')), 'latency_seconds': number(a.get('latency_seconds'))} for a in generation.get('attempts', [])]}}
    out = privacy.clean(classify(out))
    if out['trace_id'] is None:
        out['trace_id'] = hashlib.sha256(serialize({'schema_version': out['schema_version'], 'source': out['source']}).encode()).hexdigest()
    return out


def serialize(trace):
    return json.dumps(trace, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'


def save_trace(path, trace):
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize(trace), encoding='utf-8')


def validate_trace(trace):
    required = {'schema_version', 'trace_id', 'timestamp', 'source', 'query', 'routing', 'tools',
                'retrieval', 'generation', 'validation', 'abstention', 'result', 'latency',
                'lower_level', 'failure_attribution'}
    if not isinstance(trace, dict) or set(trace) != required or trace['schema_version'] != '6.1':
        raise ValueError('Unsupported unified trace schema')
    if not isinstance(trace['trace_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', trace['trace_id']):
        raise ValueError('Trace ID must be a safe identifier')
    for value in trace['generation']['token_usage'].values():
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('Token usage must be a nonnegative integer or null')
    if trace['timestamp'] is not None:
        from datetime import datetime
        parsed = datetime.fromisoformat(trace['timestamp'])
        if parsed.tzinfo is None:
            raise ValueError('Timestamp must include a timezone')
    attribution = trace['failure_attribution']
    if attribution['primary'] is not None and attribution['primary'] not in TAXONOMY:
        raise ValueError('Unknown failure taxonomy')
    if any(c not in TAXONOMY for c in attribution['categories']):
        raise ValueError('Unknown failure taxonomy')
    if attribution['primary'] is not None and attribution['primary'] not in attribution['categories']:
        raise ValueError('Primary attribution must be among categories')
    serialize(trace)
    return trace
