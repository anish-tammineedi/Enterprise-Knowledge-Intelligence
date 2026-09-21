import re
from statistics import median
from collections import Counter

from src.evaluation.dense_metrics import match_evidence


def _tokens(text):
    return re.findall(r"[a-z0-9]+(?:[.$%][a-z0-9]+)?", text.lower())


def _f1(answer, expected):
    a, e = Counter(_tokens(answer)), Counter(_tokens(expected))
    common = sum((a & e).values())
    if not common or not a or not e:
        return 0.0
    precision, recall = common / sum(a.values()), common / sum(e.values())
    return 2 * precision * recall / (precision + recall)


def _context_matches(context, question, policy):
    return {e['evidence_id'] for e in question.get('evidence', []) if match_evidence(context, e, policy)}


def evaluate_trace(question, trace, policy):
    contexts = trace.get('contexts') or []
    by_id = {c.get('context_id'): c for c in contexts}
    valid_ids = set(by_id)
    parsed = trace.get('parsed_answer')
    citations = list(trace.get('citations') or [])
    citation_valid = trace.get('status') == 'success' and set(citations) <= valid_ids
    matched = {cid: _context_matches(c, question, policy) for cid, c in by_id.items()}
    available = set().union(*matched.values()) if matched else set()
    answerable = bool(question['answerable'])
    abstained = trace.get('abstained') is True
    expected_abstention = not answerable and abstained and citation_valid
    retrieval_failure = answerable and not available
    citation_precision = None
    citation_recall = None
    if citations:
        supported = [matched.get(cid, set()) for cid in citations]
        citation_precision = sum(bool(x) for x in supported) / len(citations)
        required = {e['evidence_id'] for e in question.get('evidence', [])}
        citation_recall = len(set().union(*supported) & required) / len(required) if required else None
    answer = parsed.get('answer', '') if isinstance(parsed, dict) else ''
    expected = question.get('expected_answer', '')
    answer_f1 = _f1(answer, expected) if answerable and answer else None
    correctness = None
    if answerable and answer and not abstained:
        correctness = 'heuristic_pass' if answer_f1 >= 0.5 else 'heuristic_fail_requires_review'
    groundedness = None
    if answer and citations:
        cited_text = ' '.join(by_id[cid]['text'] for cid in citations if cid in by_id)
        groundedness = _f1(answer, cited_text) >= 0.35
    if not citation_valid and trace.get('status') == 'invalid_output':
        attribution = 'invalid_structured_output'
    elif expected_abstention:
        attribution = 'expected_abstention'
    elif retrieval_failure:
        attribution = 'retrieval_failure'
    elif answerable and abstained:
        attribution = 'generation_failure'
    elif answerable and citations and citation_precision == 0:
        attribution = 'citation_failure'
    elif answerable and correctness == 'heuristic_fail_requires_review':
        attribution = 'generation_failure'
    elif answerable and not citation_valid:
        attribution = 'citation_failure'
    elif answerable and not abstained:
        attribution = 'successful_grounded_answer' if groundedness else 'generation_failure'
    else:
        attribution = 'invalid_structured_output'
    return {'question_id': question['question_id'], 'answerable': answerable, 'status': trace.get('status'),
            'attribution': attribution, 'retrieval_evidence_present': bool(available),
            'retrieved_evidence_ids': sorted(available), 'answer_f1_heuristic': answer_f1,
            'correctness': correctness, 'groundedness_heuristic': groundedness,
            'citation_validity': citation_valid, 'citation_precision': citation_precision,
            'citation_recall': citation_recall, 'abstained': abstained,
            'expected_abstention': expected_abstention, 'latency_seconds': trace.get('latency_seconds'),
            'token_usage': trace.get('token_usage')}


def aggregate_generation(results):
    positive = [r for r in results if r['answerable']]
    negative = [r for r in results if not r['answerable']]
    valid = [r for r in results if r['status'] == 'success']
    return {'questions': len(results), 'answerable_questions': len(positive),
            'unanswerable_questions': len(negative), 'structured_output_validity': sum(r['status'] == 'success' for r in results) / len(results) if results else None,
            'answerable_false_abstention_rate': sum(r['abstained'] for r in positive) / len(positive) if positive else None,
            'unanswerable_abstention_rate': sum(r['expected_abstention'] for r in negative) / len(negative) if negative else None,
            'accepted_substantive_answer_rate': sum(r['status'] == 'success' and not r['abstained'] for r in positive) / len(positive) if positive else None,
            'citation_validity': sum(r['citation_validity'] for r in valid) / len(valid) if valid else None,
            'citation_precision': _mean([r['citation_precision'] for r in valid if r['citation_precision'] is not None]),
            'citation_recall': _mean([r['citation_recall'] for r in valid if r['citation_recall'] is not None]),
            'groundedness_heuristic': _mean([r['groundedness_heuristic'] for r in positive if r['groundedness_heuristic'] is not None]),
            'mean_latency_seconds': _mean([r['latency_seconds'] for r in results if r['latency_seconds'] is not None]),
            'median_latency_seconds': median([r['latency_seconds'] for r in results if r['latency_seconds'] is not None]) if any(r['latency_seconds'] is not None for r in results) else None,
            'input_tokens': sum((r.get('token_usage') or {}).get('input_tokens', 0) for r in results),
            'output_tokens': sum((r.get('token_usage') or {}).get('output_tokens', 0) for r in results),
            'total_tokens': sum((r.get('token_usage') or {}).get('total_tokens', 0) for r in results),
            'attribution_counts': dict(sorted(Counter(r.get('attribution', 'unspecified') for r in results).items()))}


def _mean(values):
    return sum(values) / len(values) if values else None


def select_subset(questions, per_category=2):
    selected = []
    for category in sorted({q['category'] for q in questions}):
        rows = [q for q in questions if q['category'] == category]
        for difficulty in ('easy', 'medium', 'hard'):
            candidates = [q for q in rows if q['difficulty'] == difficulty]
            if candidates and len(selected) < 100:
                selected.append(sorted(candidates, key=lambda q: q['question_id'])[0])
        if len([q for q in selected if q['category'] == category]) < per_category:
            remaining = [q for q in rows if q not in selected]
            selected.append(sorted(remaining, key=lambda q: q['question_id'])[0])
    return sorted({q['question_id']: q for q in selected}.values(), key=lambda q: q['question_id'])
