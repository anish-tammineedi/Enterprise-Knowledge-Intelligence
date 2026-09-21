import argparse
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_retrieval_benchmark import validate_benchmark
from src.embeddings.local_dense import EmbeddingCache, SentenceEncoder, digest, file_sha256, write_array, write_json
from src.evaluation.dense_metrics import aggregate, evaluate_question, grouped_metrics
from src.retrieval.dense import cosine_ranking


FROZEN_BENCHMARK_SHA256 = '74a2e70d531e389a47730e8c537329ec65cfae5134abec3739a9297feba47e86'


def verify_frozen_benchmark(path, expected=FROZEN_BENCHMARK_SHA256):
    if expected != FROZEN_BENCHMARK_SHA256 or file_sha256(path) != FROZEN_BENCHMARK_SHA256:
        raise ValueError('Frozen benchmark changed; refusing to evaluate')


def load_chunks(directory, strategy, documents):
    directory = Path(directory)
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    chunks = []
    paths = sorted(p for p in directory.glob('*.json') if p.name != 'summary.json')
    parsed_hashes = {key: digest(doc) for key, doc in documents.items()}
    for path in paths:
        envelope = json.loads(path.read_text(encoding='utf-8'))
        if envelope['experiment_id'] != summary['experiment_id'] or envelope['corpus_id'] != summary['corpus_id']:
            raise ValueError('Chunk experiment manifest mismatch')
        for chunk in envelope['chunks']:
            doc = documents[chunk['document_id']]
            if chunk['source_document_id'] != doc['document_id'] or chunk['strategy'] != strategy:
                raise ValueError('Chunk identity/strategy mismatch')
            for field in ('company', 'ticker', 'cik', 'form', 'filing_date', 'report_date',
                          'accession_number', 'source_url', 'source_sha256', 'local_path'):
                if chunk[field] != doc[field]:
                    raise ValueError(f'Chunk provenance mismatch: {field}')
            if chunk['parsed_document_sha256'] != parsed_hashes[doc['document_id']]:
                raise ValueError('Parsed document changed since chunking')
            start, end = chunk['start_char'], chunk['end_char']
            if not 0 <= start < end <= len(doc['text']) or chunk['text'] != doc['text'][start:end]:
                raise ValueError('Chunk source text/offset mismatch')
            section_ids = {s['section_id'] for s in doc['sections'] if s['start_char'] < end and s['end_char'] > start}
            if section_ids != {s['section_id'] for s in chunk['sections']}:
                raise ValueError('Chunk section provenance mismatch')
            identity = {key: chunk[key] for key in ('version', 'experiment_id', 'parsed_document_sha256',
                                                   'document_id', 'chunk_index', 'start_char', 'end_char')}
            if digest(identity) != chunk['chunk_id']:
                raise ValueError('Chunk ID/content alignment mismatch')
            chunks.append(chunk)
    chunks.sort(key=lambda c: (c['document_id'], c['chunk_index'], c['chunk_id']))
    if len(chunks) != summary['total_chunks'] or len({c['chunk_id'] for c in chunks}) != len(chunks):
        raise ValueError('Chunk count/uniqueness mismatch')
    if {c['document_id'] for c in chunks} != documents.keys():
        raise ValueError('Strategy does not cover the complete corpus')
    return chunks, paths + [directory / 'summary.json']


def ranked_result(chunk, score, rank, matches, diagnostics):
    return {**chunk, 'rank': rank, 'similarity_score': float(score),
            'filing_year': int(chunk['filing_date'][:4]), 'report_year': int(chunk['report_date'][:4]),
            'matched_evidence_ids': matches, 'embedding_diagnostics': diagnostics}


def run_experiment(root, config):
    benchmark_path = root / config['benchmark_path']
    verify_frozen_benchmark(benchmark_path, config['benchmark_sha256'])
    if config['k_values'] != [1, 3, 5, 10] or config['save_top_k'] < 10:
        raise ValueError('Baseline requires K=1,3,5,10 and saving at least 10 results')
    policy = config['evidence_match']
    if not 0 < policy['minimum_evidence_fraction'] <= 1 or not 0 < policy['strict_union_fraction'] <= 1:
        raise ValueError('Evidence fractions must be in (0,1]')
    if policy['minimum_nonwhitespace_characters'] <= 0 or config['selection_metric'] != 'recall@10':
        raise ValueError('Invalid matching or selection configuration')
    benchmark = json.loads(benchmark_path.read_text(encoding='utf-8'))
    validation = validate_benchmark(benchmark, root)
    if not validation['valid']:
        raise ValueError(f'Benchmark validation failed: {validation["errors"]}')
    parsed_paths = sorted((root / config['parsed_dir']).glob('*.json'))
    documents = {d['document_id']: d for d in (json.loads(p.read_text(encoding='utf-8')) for p in parsed_paths)}
    if set(config['chunk_dirs']) != {'fixed_size', 'recursive', 'sec_section'}:
        raise ValueError('Expected exactly the three frozen chunk strategies')
    all_chunks = {}
    protected = [benchmark_path, root / 'data/metadata/sources.json', *parsed_paths]
    for strategy, directory in sorted(config['chunk_dirs'].items()):
        all_chunks[strategy], paths = load_chunks(root / directory, strategy, documents)
        protected.extend(paths)
    frozen = {str(p.relative_to(root)): file_sha256(p) for p in protected}
    encoder = SentenceEncoder(config['model'], root / config['model_cache'])
    identity = {'config': config, 'input_sha256': frozen, 'encoder': encoder.signature}
    run_id = digest(identity)
    output = root / config['output_dir'] / run_id[:16]
    write_json(output / 'experiment.json', {**identity, 'run_id': run_id})
    cache = EmbeddingCache(root / config['embedding_cache'])
    query_records = [{'id': q['question_id'], 'text': q['question']} for q in benchmark['questions']]
    queries, query_diagnostics, query_cache = cache.encode(query_records, encoder, 'queries', 'query')
    print(f'Queries: {query_cache}', flush=True)
    write_array(output / 'query_embeddings.npy', queries)
    write_json(output / 'query_manifest.json', [dict(record, embedding_row=i, diagnostics=query_diagnostics[i])
                                               for i, record in enumerate(query_records)])
    summaries = {}
    all_results = {}
    for strategy, chunks in all_chunks.items():
        records = [{'id': c['chunk_id'], 'text': c['text']} for c in chunks]
        vectors, diagnostics, cache_stats = cache.encode(records, encoder, strategy)
        print(f'{strategy}: {len(chunks)} indexed; cache {cache_stats}', flush=True)
        destination = output / strategy
        write_array(destination / 'embeddings.npy', vectors)
        write_json(destination / 'index_manifest.json', [dict(c, embedding_row=i, embedding_diagnostics=diagnostics[i])
                                                        for i, c in enumerate(chunks)])
        results = []
        for qi, question in enumerate(benchmark['questions']):
            order, scores = cosine_ranking(queries[qi], vectors, [c['chunk_id'] for c in chunks])
            ranked = [chunks[i] for i in order]
            evaluation = evaluate_question(question, ranked, config['k_values'], policy)
            metrics, matches = evaluation if evaluation is not None else (None, [[] for _ in ranked])
            row = {'question_id': question['question_id'], 'question': question['question'],
                   'category': question['category'], 'difficulty': question['difficulty'],
                   'answerable': question['answerable'], 'multiple_documents_required': question['multiple_documents_required'],
                   'required_tickers': sorted({d['ticker'] for d in question['required_documents']}),
                   'required_documents': question['required_documents'], 'metrics': metrics,
                   'query_embedding_diagnostics': query_diagnostics[qi],
                   'results': [ranked_result(chunks[i], scores[i], rank + 1, matches[rank], diagnostics[i])
                               for rank, i in enumerate(order[:config['save_top_k']])]}
            if metrics and metrics['first_relevant_rank']:
                rank = metrics['first_relevant_rank']
                i = order[rank - 1]
                row['first_relevant_result'] = ranked_result(chunks[i], scores[i], rank, matches[rank - 1], diagnostics[i])
            results.append(row)
        positive = [r for r in results if r['answerable']]
        negative = [r for r in results if not r['answerable']]
        summary = {'indexed_chunks': len(chunks), 'embedding_dimensions': vectors.shape[1],
                   'truncated_chunks': sum(d['truncated'] for d in diagnostics),
                   'maximum_input_tokens': max(d['token_count'] for d in diagnostics),
                   'overall': aggregate(results, config['k_values']),
                   'by_group': grouped_metrics(results, config['k_values']),
                   'unanswerable_questions': len(negative),
                   'oracle_full_evidence_questions': sum(len(r['metrics']['oracle_matchable_evidence']) == len(q['evidence'])
                       for r, q in zip(results, benchmark['questions']) if q['answerable'])}
        write_json(destination / 'answerable_results.json', positive)
        write_json(destination / 'unanswerable_results.json', negative)
        write_json(destination / 'summary.json', summary)
        summaries[strategy] = summary
        all_results[strategy] = positive
        print(f'{strategy}: {json.dumps(summary["overall"], sort_keys=True)}', flush=True)
    best = sorted(summaries, key=lambda s: (-summaries[s]['overall']['recall@10'], -summaries[s]['overall']['mrr'], s))[0]
    worst = sorted(all_results[best], key=lambda r: (r['metrics']['recall@10'], r['metrics']['reciprocal_rank'], r['question_id']))[:10]
    write_json(output / 'worst_failures.json', {'strategy': best, 'sort': ['recall@10 ascending', 'reciprocal_rank ascending', 'question_id'], 'questions': worst})
    changed = [path for path, before in frozen.items() if file_sha256(root / path) != before]
    if changed:
        raise ValueError(f'Protected inputs changed during evaluation: {changed}')
    summary = {'run_id': run_id, 'model': encoder.signature, 'benchmark_sha256': frozen[config['benchmark_path']],
               'benchmark_unchanged': True, 'protected_inputs_unchanged': True,
               'best_strategy_by_recall_at_10_then_mrr': best, 'strategies': summaries,
               'truncated_queries': sum(d['truncated'] for d in query_diagnostics)}
    write_json(output / 'summary.json', summary)
    print(f'Complete experiment: {output}', flush=True)
    return output, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the frozen SEC dense retrieval baseline')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--config', type=Path, default=Path('configs/dense_retrieval.json'))
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        config = json.loads((root / args.config).read_text(encoding='utf-8'))
        run_experiment(root, config)
    except (OSError, ValueError, KeyError) as error:
        print(f'Dense retrieval failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
