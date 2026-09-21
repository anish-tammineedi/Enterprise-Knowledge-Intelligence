import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {
    'direct_factual', 'section_specific', 'numerical', 'temporal', 'cross_document',
    'comparative', 'multi_hop', 'table_oriented', 'unanswerable', 'ambiguous_adversarial',
}
METADATA = ('document_id', 'company', 'ticker', 'cik', 'form', 'filing_date',
            'report_date', 'accession_number', 'source_url')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def normalized(value):
    return re.sub(r'\s+', ' ', value).strip().casefold()


def validate_question(question, documents):
    require(isinstance(question, dict), 'Question must be an object')
    require(bool(re.fullmatch(r'SEC-\d{3}', question['question_id'])), 'Invalid question ID')
    require(nonempty(question['question']), 'Missing question text')
    require(question['category'] in CATEGORIES, 'Unknown category')
    require(question['difficulty'] in {'easy', 'medium', 'hard'}, 'Unknown difficulty')
    require(type(question['answerable']) is bool, 'answerable must be boolean')
    require(type(question['multiple_documents_required']) is bool, 'multi-document label must be boolean')
    require(nonempty(question['acceptable_answer_variants']), 'Missing acceptable-answer notes')
    require(question['review_status'] in {'source_checked', 'manual_review_recommended'}, 'Invalid review status')
    require(nonempty(question['review_notes']), 'Missing review notes')
    required = question['required_documents']
    evidence = question['evidence']
    require(isinstance(required, list) and isinstance(evidence, list), 'References and evidence must be lists')
    ids = [ref['document_id'] for ref in required]
    require(len(ids) == len(set(ids)), 'Duplicate required document')
    require(set(ids) <= documents.keys(), 'Unknown document reference')
    require(question['multiple_documents_required'] == (len(ids) > 1), 'Incorrect multi-document label')
    scope = question['query_scope']
    require(isinstance(scope['tickers'], list) and isinstance(scope['report_years'], list), 'Invalid query scope')
    require(set(scope['tickers']) <= {d['ticker'] for d in documents.values()}, 'Invalid query ticker')
    require(all(type(year) is int and 1900 <= year <= 2200 for year in scope['report_years']), 'Invalid query year')
    require(bool(scope['report_years']), 'Missing query years')
    if question['answerable']:
        require(nonempty(question['expected_answer']), 'Answerable question lacks expected answer')
        require(bool(ids) and bool(evidence), 'Answerable question lacks evidence or documents')
        require(question['unanswerable_reason'] is None and question['absence_audit'] is None,
                'Answerable question has an absence justification')
        require(question['category'] != 'unanswerable', 'Answerable item in unanswerable category')
        require(set(scope['tickers']) == {documents[i]['ticker'] for i in ids}, 'Query tickers disagree with evidence')
        require(set(scope['report_years']) == {int(documents[i]['report_date'][:4]) for i in ids},
                'Query years disagree with required filings')
        require(scope['outside_corpus_company'] is None, 'Answerable question has an unsupported company')
        answer = normalized(question['expected_answer']).rstrip('.')
        require(len(answer) < 8 or answer not in normalized(question['question']),
                'Full expected answer appears in question text; review leakage')
    else:
        require(question['category'] == 'unanswerable', 'Unanswerable item has wrong category')
        require(question['expected_answer'] is None, 'Unanswerable question must have null answer')
        require(not ids and not evidence, 'Unanswerable question must not assert supporting evidence')
        require(nonempty(question['unanswerable_reason']), 'Missing unanswerable reason')
        require(bool(scope['tickers']) or nonempty(scope['outside_corpus_company']), 'Missing unsupported query target')
        audit = question['absence_audit']
        require(isinstance(audit, dict), 'Missing absence audit')
        require(isinstance(audit['document_ids'], list) and bool(audit['document_ids'])
                and set(audit['document_ids']) <= documents.keys(), 'Invalid absence-audit documents')
        require(isinstance(audit['search_terms'], list) and bool(audit['search_terms'])
                and all(nonempty(term) for term in audit['search_terms']), 'Missing absence search terms')
        require(nonempty(audit['inspection_notes']), 'Missing absence inspection notes')
    for ref in required:
        doc = documents[ref['document_id']]
        for field in METADATA:
            require(ref[field] == doc[field], f'Incorrect reference {field}')
        require(type(ref['filing_year']) is int and ref['filing_year'] == int(doc['filing_date'][:4]),
                'Incorrect filing year')
        require(type(ref['report_year']) is int and ref['report_year'] == int(doc['report_date'][:4]),
                'Incorrect report year')
        require(isinstance(ref['items'], list) and bool(ref['items']), 'Missing relevant Items')
        require(set(ref['items']) == {e['item'] for e in evidence if e['document_id'] == ref['document_id']},
                'Relevant Items disagree with evidence')
    evidence_ids = [entry['evidence_id'] for entry in evidence]
    require(len(evidence_ids) == len(set(evidence_ids)), 'Duplicate evidence IDs')
    require(set(ids) == {entry['document_id'] for entry in evidence}, 'Required documents disagree with evidence')
    for entry in evidence:
        require(nonempty(entry['evidence_id']), 'Missing evidence ID')
        doc = documents[entry['document_id']]
        for field in ('accession_number', 'ticker', 'company', 'source_url'):
            require(entry[field] == doc[field], f'Incorrect evidence {field}')
        start, end = entry['start_char'], entry['end_char']
        require(type(start) is int and type(end) is int and 0 <= start < end <= len(doc['text']),
                'Invalid evidence offsets')
        require(nonempty(entry['text']) and doc['text'][start:end] == entry['text'], 'Evidence text does not exist at offsets')
        sections = [s for s in doc['sections'] if s['section_id'] == entry['section_id']]
        require(len(sections) == 1, 'Unknown evidence section')
        section = sections[0]
        require(entry['item'] == section['item'] and entry['section_name'] == section['name'], 'Wrong SEC Item or section name')
        require(section['start_char'] <= start < end <= section['end_char'], 'Evidence crosses section boundary')
        indices = entry['content_block_indices']
        require(isinstance(indices, list) and bool(indices), 'Missing evidence block references')
        require(all(type(i) is int and 0 <= i < len(doc['content']) for i in indices), 'Invalid content block index')
        require(indices == list(range(indices[0], indices[-1] + 1)), 'Evidence blocks must be consecutive')
        blocks = [doc['content'][i] for i in indices]
        require(start == blocks[0]['start_char'] and end == blocks[-1]['end_char'], 'Evidence/block offsets disagree')
        require(type(entry['contains_table']) is bool
                and entry['contains_table'] == any(b['type'] == 'table' for b in blocks), 'Wrong table label')
    if question['category'] in {'cross_document', 'comparative'}:
        require(len(ids) >= 2, 'Cross-document/comparative item needs multiple filings')
    if question['category'] == 'multi_hop':
        require(len({(e['document_id'], i) for e in evidence for i in e['content_block_indices']}) >= 2,
                'Multi-hop item needs multiple source blocks')
    if question['category'] == 'table_oriented':
        require(any(e['contains_table'] for e in evidence), 'Table-oriented item lacks table evidence')


def validate_benchmark(benchmark, root=ROOT):
    root = Path(root)
    errors = []
    documents = {}
    try:
        require(isinstance(benchmark, dict), 'Benchmark must be an object')
        require(benchmark['schema_version'] == '1.0', 'Unsupported schema version')
        for field in ('benchmark_id', 'construction_basis', 'evidence_policy', 'offset_convention'):
            require(nonempty(benchmark[field]), f'Missing {field}')
        sources = json.loads((root / 'data/metadata/sources.json').read_text(encoding='utf-8'))['documents']
        source_by_accession = {d['accession_number']: d for d in sources}
        for path in sorted((root / 'data/processed/parsed').glob('*.json')):
            doc = json.loads(path.read_text(encoding='utf-8'))
            require(doc['document_id'] not in documents, 'Duplicate corpus document ID')
            require(doc['accession_number'] in source_by_accession, 'Parsed accession absent from sources.json')
            source = source_by_accession[doc['accession_number']]
            for field in METADATA:
                require(nonempty(doc[field]), f'Invalid corpus {field}')
                if field != 'document_id':
                    require(doc[field] == source[field], f'Parsed/source metadata mismatch: {field}')
            date.fromisoformat(doc['filing_date'])
            date.fromisoformat(doc['report_date'])
            documents[doc['document_id']] = doc
        require(bool(documents), 'Parsed corpus is empty')
        manifest = benchmark['corpus']
        require(isinstance(manifest, list), 'Corpus manifest must be a list')
        manifest_ids = [entry['document_id'] for entry in manifest]
        require(len(manifest_ids) == len(set(manifest_ids)), 'Duplicate manifest document')
        require(set(manifest_ids) == documents.keys(), 'Manifest does not match current parsed corpus')
        for entry in manifest:
            doc = documents[entry['document_id']]
            for field in METADATA + ('source_sha256',):
                require(entry[field] == doc[field], f'Manifest mismatch: {field}')
            require(entry['text_sha256'] == hashlib.sha256(doc['text'].encode('utf-8')).hexdigest(), 'Corpus text changed')
            require(entry['parsed_path'] == f"data/processed/parsed/{doc['document_id']}.json", 'Invalid parsed path')
        questions = benchmark['questions']
        require(isinstance(questions, list) and bool(questions), 'Missing questions')
        targets = benchmark['category_targets']
        require(set(targets) == CATEGORIES and all(type(n) is int and n > 0 for n in targets.values()),
                'Invalid category targets')
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return {'valid': False, 'errors': [f'Benchmark/corpus: {error}']}
    ids = set()
    texts = set()
    for index, question in enumerate(questions):
        label = question.get('question_id', f'index {index}') if isinstance(question, dict) else f'index {index}'
        try:
            validate_question(question, documents)
            require(question['question_id'] not in ids, 'Duplicate question ID')
            require(normalized(question['question']) not in texts, 'Duplicate question text')
            ids.add(question['question_id'])
            texts.add(normalized(question['question']))
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as error:
            errors.append(f'{label}: {error}')
    if errors:
        return {'valid': False, 'errors': errors}
    category_counts = dict(sorted(Counter(q['category'] for q in questions).items()))
    if category_counts != targets:
        errors.append('Category distribution does not match declared targets')
    evidence_docs = Counter(ref['document_id'] for q in questions for ref in q['required_documents'])
    if set(evidence_docs) != documents.keys():
        errors.append('Not every corpus document has answerable benchmark coverage')
    summary = {
        'valid': not errors, 'errors': errors, 'benchmark_id': benchmark['benchmark_id'],
        'question_count': len(questions), 'category_counts': category_counts,
        'difficulty_counts': dict(sorted(Counter(q['difficulty'] for q in questions).items())),
        'answerable_count': sum(q['answerable'] for q in questions),
        'unanswerable_count': sum(not q['answerable'] for q in questions),
        'single_document_count': sum(len(q['required_documents']) == 1 for q in questions),
        'multi_document_count': sum(q['multiple_documents_required'] for q in questions),
        'no_supporting_document_count': sum(not q['required_documents'] for q in questions),
        'questions_per_document': dict(sorted(evidence_docs.items())),
        'questions_with_table_evidence': sum(any(e['contains_table'] for e in q['evidence']) for q in questions),
        'evidence_span_count': sum(len(q['evidence']) for q in questions),
        'manual_review_recommended': [q['question_id'] for q in questions if q['review_status'] == 'manual_review_recommended'],
        'validation_scope': 'Checks structure and exact corpus evidence, not semantic correctness, exhaustive relevance, or proof of absence.',
    }
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description='Validate SEC retrieval benchmark ground truth')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--benchmark', type=Path, default=Path('evals/ground_truth/sec_retrieval_benchmark.json'))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    try:
        benchmark = json.loads((args.root / args.benchmark).read_text(encoding='utf-8'))
        result = validate_benchmark(benchmark, args.root)
    except (OSError, ValueError) as error:
        print(f'Unable to validate benchmark: {error}', file=sys.stderr)
        return 1
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    print(payload, end='')
    if args.report:
        try:
            path = args.root / args.report
            require(path.resolve() != (args.root / args.benchmark).resolve(), 'Report must not overwrite benchmark')
            if not path.exists() or path.read_text(encoding='utf-8') != payload:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix + '.tmp')
                temporary.write_text(payload, encoding='utf-8')
                temporary.replace(path)
        except (OSError, ValueError) as error:
            print(f'Unable to write report: {error}', file=sys.stderr)
            return 1
    return 0 if result['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
