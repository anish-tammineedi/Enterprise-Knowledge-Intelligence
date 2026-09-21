import argparse
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_dense_retrieval import load_chunks, verify_frozen_benchmark
from src.embeddings.local_dense import digest, file_sha256, write_json
from src.evaluation.dense_metrics import aggregate, evaluate_question, grouped_metrics
from src.retrieval.dense import cosine_ranking
from src.retrieval.lexical import BM25, TOKENIZER_VERSION, reciprocal_rank_fusion


def complementarity(systems):
    rows = {system: {r['question_id']: r for r in results if r['answerable']} for system, results in systems.items()}
    solved = {system: {qid for qid, r in values.items() if r['metrics']['recall@10'] == 1} for system, values in rows.items()}
    dense, lexical, hybrid = (solved[name] for name in ('dense', 'bm25', 'hybrid'))
    universe = set(rows['dense'])
    groups = {'dense_not_bm25': dense - lexical, 'bm25_not_dense': lexical - dense,
              'hybrid_only': hybrid - dense - lexical, 'missed_by_all': universe - dense - lexical - hybrid,
              'dense_solved': dense, 'bm25_solved': lexical, 'hybrid_solved': hybrid,
              'both_standalone_solved': dense & lexical,
              'standalone_solved_hybrid_missed': (dense | lexical) - hybrid,
              'zero_evidence_all': {qid for qid in universe if all(rows[s][qid]['metrics']['recall@10'] == 0 for s in rows)}}
    evidence = []
    for qid in sorted(universe):
        recovered = {s: set(rows[s][qid]['metrics']['recovered_evidence@10']) for s in rows}
        evidence.append({'question_id': qid, 'recall@10': {s: rows[s][qid]['metrics']['recall@10'] for s in rows},
                         'bm25_evidence_not_dense': sorted(recovered['bm25'] - recovered['dense']),
                         'dense_evidence_not_bm25': sorted(recovered['dense'] - recovered['bm25']),
                         'hybrid_evidence_not_standalone': sorted(recovered['hybrid'] - recovered['dense'] - recovered['bm25'])})
    return {'solved_definition': 'All frozen evidence entries recovered at 10 (recall@10 == 1)',
            'groups': {key: {'count': len(value), 'question_ids': sorted(value)} for key, value in groups.items()},
            'per_question_evidence': evidence}


def run_experiment(root, config):
    dense_path = root / config['dense_run']
    original = json.loads((dense_path / 'experiment.json').read_text())
    dense_config = original['config']
    benchmark_path = root / dense_config['benchmark_path']
    verify_frozen_benchmark(benchmark_path, dense_config['benchmark_sha256'])
    if config['bm25']['tokenizer'] != TOKENIZER_VERSION or config['bm25']['query_term_frequency'] != 'binary':
        raise ValueError('Unsupported tokenizer/query weighting')
    if config['save_top_k'] < 10 or config['selection_metric'] != 'recall@10' or config['complementarity_solved'] != 'recall@10 == 1':
        raise ValueError('Invalid reporting configuration')
    if config['rrf']['candidate_depth'] is not None and config['rrf']['candidate_depth'] < 100:
        raise ValueError('Candidate depth must be at least 100 or null for full rankings')
    protected = dict(original['input_sha256'])
    for path in dense_path.rglob('*'):
        if path.is_file():
            protected[str(path.relative_to(root))] = file_sha256(path)
    if any(file_sha256(root / path) != expected for path, expected in protected.items()):
        raise ValueError('Frozen dense input hashes changed')
    questions = json.loads(benchmark_path.read_text())['questions']
    documents = {d['document_id']: d for d in (json.loads(p.read_text()) for p in (root / dense_config['parsed_dir']).glob('*.json'))}
    queries = np.load(dense_path / 'query_embeddings.npy', allow_pickle=False)
    query_manifest = json.loads((dense_path / 'query_manifest.json').read_text())
    if queries.shape != (len(questions), dense_config['model']['dimensions']):
        raise ValueError('Query matrix shape mismatch')
    for i, (q, entry) in enumerate(zip(questions, query_manifest)):
        if entry['id'] != q['question_id'] or entry['text'] != q['question'] or entry['embedding_row'] != i:
            raise ValueError('Query alignment mismatch')
    if len(query_manifest) != len(questions):
        raise ValueError('Query manifest length mismatch')
    source_paths = ['src/retrieval/lexical.py', 'scripts/run_lexical_hybrid.py', 'src/evaluation/dense_metrics.py', 'src/retrieval/dense.py']
    identity = {'config': config, 'dense_config': dense_config, 'input_sha256': protected,
                'source_sha256': {path: file_sha256(root / path) for path in source_paths},
                'numpy_version': np.__version__}
    run_id = digest(identity)
    output = root / config['output_dir'] / run_id[:16]
    write_json(output / 'experiment.json', dict(identity, run_id=run_id))
    summaries, all_results, complements = {}, {}, {}
    ks, policy = dense_config['k_values'], dense_config['evidence_match']
    for strategy, directory in sorted(dense_config['chunk_dirs'].items()):
        chunks, _ = load_chunks(root / directory, strategy, documents)
        ids = [c['chunk_id'] for c in chunks]
        positions = {identifier: i for i, identifier in enumerate(ids)}
        manifest = json.loads((dense_path / strategy / 'index_manifest.json').read_text())
        matrix = np.load(dense_path / strategy / 'embeddings.npy', allow_pickle=False)
        if matrix.shape != (len(chunks), queries.shape[1]) or len(manifest) != len(chunks):
            raise ValueError('Dense index shape mismatch')
        for i, (c, entry) in enumerate(zip(chunks, manifest)):
            if entry['embedding_row'] != i or any(entry[key] != value for key, value in c.items()):
                raise ValueError('Dense chunk alignment mismatch')
        lexical = BM25([c['text'] for c in chunks], ids, config['bm25']['k1'], config['bm25']['b'])
        systems = {key: [] for key in ('dense', 'bm25', 'hybrid')}
        original_rows = {r['question_id']: r for r in json.loads((dense_path / strategy / 'answerable_results.json').read_text())}
        for qi, q in enumerate(questions):
            dense_order, dense_scores = cosine_ranking(queries[qi], matrix, ids)
            bm25_order, bm25_scores = lexical.rank(q['question'])
            dense_ids, bm25_ids = ([ids[i] for i in order] for order in (dense_order, bm25_order))
            hybrid_ids, hybrid_scores = reciprocal_rank_fusion([dense_ids, bm25_ids], **config['rrf'])
            source_ranks = {'dense': {identifier: i for i, identifier in enumerate(dense_ids, 1)},
                            'bm25': {identifier: i for i, identifier in enumerate(bm25_ids, 1)}}
            for system, order in [('dense', dense_ids), ('bm25', bm25_ids), ('hybrid', hybrid_ids)]:
                ranked = [chunks[positions[identifier]] for identifier in order]
                evaluation = evaluate_question(q, ranked, ks, policy)
                metrics, matches = evaluation if evaluation else (None, [[] for _ in ranked])
                if system == 'dense' and q['answerable'] and metrics != original_rows[q['question_id']]['metrics']:
                    raise ValueError('Dense baseline metric drift')
                def result(rank):
                    identifier = order[rank - 1]
                    i = positions[identifier]
                    score = {'dense': dense_scores[i], 'bm25': bm25_scores[i], 'hybrid': hybrid_scores.get(identifier, 0)}[system]
                    return {**chunks[i], 'rank': rank, 'score': float(score), 'score_type': system,
                            'dense_score': float(dense_scores[i]), 'bm25_score': float(bm25_scores[i]),
                            'dense_rank': source_ranks['dense'][identifier], 'bm25_rank': source_ranks['bm25'][identifier],
                            'filing_year': int(chunks[i]['filing_date'][:4]), 'report_year': int(chunks[i]['report_date'][:4]),
                            'matched_evidence_ids': matches[rank - 1]}
                row = {'question_id': q['question_id'], 'question': q['question'], 'category': q['category'],
                       'difficulty': q['difficulty'], 'answerable': q['answerable'],
                       'multiple_documents_required': q['multiple_documents_required'],
                       'required_tickers': sorted({d['ticker'] for d in q['required_documents']}),
                       'required_documents': q['required_documents'], 'metrics': metrics,
                       'ranked_candidates': len(order), 'positive_bm25_candidates': int(np.count_nonzero(bm25_scores)),
                       'results': [result(rank) for rank in range(1, min(config['save_top_k'], len(order)) + 1)]}
                if metrics and metrics['first_relevant_rank']:
                    row['first_relevant_result'] = result(metrics['first_relevant_rank'])
                systems[system].append(row)
        summaries[strategy] = {}
        for system, rows in systems.items():
            dest = output / strategy / system
            summary = {'indexed_chunks': len(chunks), 'overall': aggregate(rows, ks), 'by_group': grouped_metrics(rows, ks),
                       'unanswerable_questions': 10,
                       'zero_score_bm25_top10_questions': [r['question_id'] for r in rows if any(c['bm25_score'] == 0 for c in r['results'])] if system == 'bm25' else []}
            write_json(dest / 'answerable_results.json', [r for r in rows if r['answerable']])
            write_json(dest / 'unanswerable_results.json', [r for r in rows if not r['answerable']])
            write_json(dest / 'summary.json', summary)
            summaries[strategy][system] = summary
            print(strategy, system, 'Recall@10', summary['overall']['recall@10'], 'MRR', summary['overall']['mrr'], flush=True)
        complements[strategy] = complementarity(systems)
        all_results[strategy] = systems
    best = sorted(summaries, key=lambda st: (-summaries[st]['hybrid']['overall']['recall@10'], -summaries[st]['hybrid']['overall']['mrr'], st))[0]
    worst = sorted([r for r in all_results[best]['hybrid'] if r['answerable']], key=lambda r: (r['metrics']['recall@10'], r['metrics']['reciprocal_rank'], r['question_id']))[:10]
    write_json(output / 'worst_hybrid_failures.json', {'strategy': best, 'questions': worst})
    write_json(output / 'complementarity.json', complements)
    if any(file_sha256(root / path) != expected for path, expected in protected.items()):
        raise ValueError('Protected inputs changed during evaluation')
    summary = {'run_id': run_id, 'strategies': summaries, 'best_hybrid_by_recall10_then_mrr': best,
               'benchmark_unchanged': True, 'protected_inputs_unchanged': True, 'dense_metrics_reproduced': True}
    write_json(output / 'summary.json', summary)
    print('Complete experiment:', output, flush=True)
    return output, summary


def main():
    parser = argparse.ArgumentParser(description='Evaluate BM25 and RRF against the frozen dense baseline')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--config', type=Path, default=Path('configs/lexical_hybrid.json'))
    args = parser.parse_args()
    root = args.root.resolve()
    run_experiment(root, json.loads((root / args.config).read_text()))


if __name__ == '__main__':
    main()
