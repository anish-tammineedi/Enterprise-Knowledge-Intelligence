from collections import defaultdict


PROVENANCE = ('document_id', 'accession_number', 'ticker', 'company', 'source_url')


def evidence_overlap(chunk, evidence):
    if any(chunk.get(key) != evidence.get(key) for key in PROVENANCE):
        return 0, None
    if evidence['section_id'] not in {s['section_id'] for s in chunk['sections']}:
        return 0, None
    start = max(chunk['start_char'], evidence['start_char'])
    end = min(chunk['end_char'], evidence['end_char'])
    if start >= end:
        return 0, None
    part = evidence['text'][start - evidence['start_char']:end - evidence['start_char']]
    if chunk['text'][start - chunk['start_char']:end - chunk['start_char']] != part:
        return 0, None
    count = sum(not char.isspace() for char in part)
    return count, (start, end)


def match_evidence(chunk, evidence, policy):
    count, interval = evidence_overlap(chunk, evidence)
    total = sum(not char.isspace() for char in evidence['text'])
    required = max(min(policy['minimum_nonwhitespace_characters'], total),
                   policy['minimum_evidence_fraction'] * total)
    return total > 0 and count >= required


def union_fraction(chunks, evidence):
    intervals = sorted(interval for chunk in chunks for count, interval in [evidence_overlap(chunk, evidence)] if count)
    cursor = evidence['start_char']
    covered = 0
    for start, end in intervals:
        start = max(start, cursor)
        if start < end:
            covered += sum(not c.isspace() for c in evidence['text'][start-evidence['start_char']:end-evidence['start_char']])
        cursor = max(cursor, end)
    total = sum(not c.isspace() for c in evidence['text'])
    return covered / total if total else 0


def evaluate_question(question, ranked_chunks, k_values, policy):
    if not question['answerable']:
        return None
    evidence = question['evidence']
    matches = [[e['evidence_id'] for e in evidence if match_evidence(chunk, e, policy)] for chunk in ranked_chunks]
    first = next((rank for rank, found in enumerate(matches, 1) if found), None)
    metrics = {'reciprocal_rank': 1 / first if first else 0, 'first_relevant_rank': first,
               'oracle_matchable_evidence': sorted({e for found in matches for e in found})}
    doc_for_evidence = {e['evidence_id']: e['document_id'] for e in evidence}
    required_docs = {d['document_id'] for d in question['required_documents']}
    for k in k_values:
        recovered = {e for found in matches[:k] for e in found}
        recovered_docs = {doc_for_evidence[e] for e in recovered}
        metrics[f'recall@{k}'] = len(recovered) / len(evidence)
        metrics[f'hit_rate@{k}'] = int(bool(recovered))
        metrics[f'complete_evidence@{k}'] = int(len(recovered) == len(evidence))
        metrics[f'multi_document_complete_recall@{k}'] = (
            int(required_docs <= recovered_docs) if question['multiple_documents_required'] else None)
        metrics[f'strict_union_recall@{k}'] = sum(union_fraction(ranked_chunks[:k], e) >= policy['strict_union_fraction'] for e in evidence) / len(evidence)
        metrics[f'recovered_evidence@{k}'] = sorted(recovered)
        metrics[f'recovered_documents@{k}'] = sorted(recovered_docs)
    return metrics, matches


def aggregate(results, k_values):
    positive = [r for r in results if r['answerable']]
    multi = [r for r in positive if r['multiple_documents_required']]
    summary = {'answerable_questions': len(positive), 'multi_document_questions': len(multi)}
    summary['mrr'] = sum(r['metrics']['reciprocal_rank'] for r in positive) / len(positive) if positive else None
    for k in k_values:
        for key in ('recall', 'hit_rate', 'complete_evidence', 'strict_union_recall'):
            name = f'{key}@{k}'
            summary[name] = sum(r['metrics'][name] for r in positive) / len(positive) if positive else None
        name = f'multi_document_complete_recall@{k}'
        summary[name] = sum(r['metrics'][name] for r in multi) / len(multi) if multi else None
    return summary


def grouped_metrics(results, k_values):
    groups = {name: defaultdict(list) for name in ('category', 'difficulty', 'ticker')}
    for result in results:
        if not result['answerable']:
            continue
        groups['category'][result['category']].append(result)
        groups['difficulty'][result['difficulty']].append(result)
        for ticker in result['required_tickers']:
            groups['ticker'][ticker].append(result)
    return {name: {key: aggregate(rows, k_values) for key, rows in sorted(values.items())}
            for name, values in groups.items()}
