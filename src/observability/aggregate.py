from collections import Counter
import math
from statistics import mean, median

from src.observability.trace import number, TAXONOMY, validate_trace


def rate(values):
    known = [v for v in values if type(v) is bool]
    return {'value': sum(known) / len(known) if known else None,
            'numerator': sum(known), 'denominator': len(known), 'unavailable': len(values) - len(known)}


def distribution(values):
    known = sorted(v for v in values if number(v) is not None)
    return {'count': len(known), 'unavailable': len(values) - len(known),
            'mean': mean(known) if known else None, 'median': median(known) if known else None,
            'p95': known[math.ceil(0.95 * len(known)) - 1] if known else None}


def aggregate(traces):
    unique = {}
    for trace in traces:
        validate_trace(trace)
        identity = trace['trace_id']
        if identity in unique and unique[identity] != trace:
            raise ValueError('Conflicting traces share an ID')
        unique[identity] = trace
    rows = [unique[k] for k in sorted(unique)]
    tools = [t for r in rows for t in r['tools']]
    retrieval = [r for r in rows if r['retrieval']['evidence'] or 'document_retrieval' in (r['routing']['tools_selected'] or []) or r['source']['kind'] == 'phase4b']
    categories = Counter(c for r in rows for c in r['failure_attribution']['categories'])
    primary = Counter(r['failure_attribution']['primary'] for r in rows if r['failure_attribution']['primary'] is not None)
    tokens = {}
    for key in ('input_tokens', 'output_tokens', 'total_tokens'):
        known = [r['generation']['token_usage'][key] for r in rows if r['generation']['token_usage'][key] is not None]
        tokens[key] = {'known_sum': sum(known) if known else None, 'known_mean': mean(known) if known else None,
                       'total': sum(known) if known and len(known) == len(rows) else None,
                       'average': mean(known) if known and len(known) == len(rows) else None,
                       'count': len(known), 'unavailable': len(rows) - len(known)}
    return {'schema_version': '6.1', 'total_queries': len(rows),
            'telemetry_coverage': {'routing_queries': sum(r['routing']['tools_selected'] is not None for r in rows),
                                   'queries_with_tool_records': sum(bool(r['tools']) for r in rows),
                                   'timestamps': sum(r['timestamp'] is not None for r in rows)},
            'routing_success_rate': rate([r['routing']['correct'] for r in rows]),
            'tool_success_rate': rate([t['status'] == 'success' if t['status'] is not None else None for t in tools]),
            'retrieval_evidence_sufficiency_rate': rate([r['retrieval']['evidence_sufficient'] for r in retrieval]),
            'retrieval_sufficiency_by_basis': {basis: rate([r['retrieval']['evidence_sufficient'] for r in retrieval if r['retrieval']['sufficiency_basis'] == basis]) for basis in sorted({r['retrieval']['sufficiency_basis'] for r in retrieval if r['retrieval']['sufficiency_basis'] is not None})},
            'structured_output_validity': rate([r['validation']['json_schema_valid'] for r in rows]),
            'output_contract_validity': rate([r['validation']['output_contract_valid'] for r in rows]),
            'abstention_rate': rate([r['abstention']['observed'] for r in rows]),
            'expected_abstention_accuracy': rate([r['abstention']['correct'] for r in rows if r['abstention']['expected'] is True]),
            'abstention_label_accuracy': rate([r['abstention']['correct'] for r in rows]),
            'citation_validation_rate': rate([r['validation']['citation_valid'] for r in rows]),
            'primary_failure_counts': {k: primary[k] for k in TAXONOMY},
            'all_failure_counts': {k: categories[k] for k in TAXONOMY},
            'classification_unavailable': sum(r['failure_attribution']['primary'] is None for r in rows),
            'latency_seconds': {'end_to_end': distribution([r['latency']['end_to_end_seconds'] for r in rows]),
                                'retrieval': distribution([r['retrieval']['latency_seconds'] for r in retrieval]),
                                'generation': distribution([r['generation']['latency_seconds'] for r in rows]),
                                'recorded_by_scope': {scope: distribution([r['latency']['recorded_seconds'] for r in rows if r['latency']['recorded_scope'] == scope]) for scope in sorted({r['latency']['recorded_scope'] for r in rows if r['latency']['recorded_scope'] is not None})}},
            'tokens': tokens,
            'definitions': {'p95': 'nearest rank ceil(0.95*n), sorted known observations',
                            'failure_counts': 'primary counts are exclusive; all_failure_counts overlap',
                            'missing_values': 'null means unavailable, never replaced with zero',
                            'tool_denominator': 'invoked tools only; historical missing tools excluded',
                            'citation_validation': 'contract/provenance validity, not semantic claim support; valid empty abstention citations count as valid',
                            'total_queries': 'unique trace IDs, not unique query text'}}
