import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_dense_retrieval import load_chunks, verify_frozen_benchmark
from src.embeddings.local_dense import digest, file_sha256, write_json
from src.evaluation.dense_metrics import aggregate, grouped_metrics
from src.retrieval.dense import cosine_ranking
from src.retrieval.lexical import BM25, reciprocal_rank_fusion
from src.retrieval.reranking import LocalReranker, PairScoreCache, analyze, rerank


def summarize_analysis(rows):
    positive = [r for r in rows if r['answerable']]
    multi = [r for r in positive if r['multiple_documents_required']]
    out = {key: sum(r['analysis'][key] for r in positive) / len(positive)
           for key in ['oracle_evidence_recall', 'oracle_any_evidence', 'oracle_all_evidence']}
    out['oracle_multi_document_complete'] = sum(r['analysis']['oracle_all_documents'] for r in multi) / len(multi)
    out['failure_classes'] = dict(sorted(Counter(r['analysis']['failure_class'] for r in positive).items()))
    out['movement'] = {}
    for name in ['promoted_into_top1', 'promoted_into_top3', 'promoted_into_top5', 'demoted_out_of_top5']:
        out['movement'][name] = {'chunk_query_pairs': sum(len(r['analysis']['movement'][name]) for r in positive),
                                 'question_ids': [r['question_id'] for r in positive if r['analysis']['movement'][name]]}
    out['questions_by_recall_change'] = {}
    for k in ['1', '3', '5', '10']:
        out['questions_by_recall_change'][k] = {label: [r['question_id'] for r in positive if (r['analysis']['recall_delta'][k] > 0) - (r['analysis']['recall_delta'][k] < 0) == sign]
                                              for label, sign in [('improved', 1), ('harmed', -1), ('unchanged', 0)]}
    return out


def run_experiment(root, config):
    start = time.perf_counter()
    if config['strategy'] != 'sec_section' or config['candidate_sources'] != ['bm25', 'hybrid']:
        raise ValueError('This baseline evaluates section-aware BM25 and hybrid')
    if config['candidate_depths'] != [20, 50] or config['selection_metric'] != 'mrr':
        raise ValueError('Baseline requires depths 20 and 50 and descriptive selection by MRR')
    previous = root / config['phase3c_run']
    previous_experiment = json.loads((previous / 'experiment.json').read_text())
    dense_config = previous_experiment['dense_config']
    dense_path = root / previous_experiment['config']['dense_run']
    protected = dict(previous_experiment['input_sha256'])
    protected.update(previous_experiment['source_sha256'])
    for path in previous.rglob('*'):
        if path.is_file():
            protected[str(path.relative_to(root))] = file_sha256(path)
    if any(file_sha256(root / path) != value for path, value in protected.items()):
        raise ValueError('Prior phase inputs changed')
    benchmark_path = root / dense_config['benchmark_path']
    verify_frozen_benchmark(benchmark_path)
    questions = json.loads(benchmark_path.read_text())['questions']
    documents = {d['document_id']: d for d in (json.loads(p.read_text()) for p in (root / dense_config['parsed_dir']).glob('*.json'))}
    chunks, _ = load_chunks(root / dense_config['chunk_dirs']['sec_section'], 'sec_section', documents)
    ids = [c['chunk_id'] for c in chunks]
    position = {identifier: i for i, identifier in enumerate(ids)}
    matrix = np.load(dense_path / 'sec_section/embeddings.npy', allow_pickle=False)
    queries = np.load(dense_path / 'query_embeddings.npy', allow_pickle=False)
    manifest = json.loads((dense_path / 'sec_section/index_manifest.json').read_text())
    query_manifest = json.loads((dense_path / 'query_manifest.json').read_text())
    if len(manifest) != len(chunks) or len(query_manifest) != len(questions):
        raise ValueError('Dense manifests changed')
    for i, c in enumerate(chunks):
        if manifest[i]['embedding_row'] != i or any(manifest[i][key] != value for key, value in c.items()):
            raise ValueError('Chunk alignment changed')
    for i, q in enumerate(questions):
        if query_manifest[i]['embedding_row'] != i or query_manifest[i]['id'] != q['question_id'] or query_manifest[i]['text'] != q['question']:
            raise ValueError('Question alignment changed')
    lexical = BM25([c['text'] for c in chunks], ids, **{k: previous_experiment['config']['bm25'][k] for k in ['k1', 'b']})
    scorer = LocalReranker(config['model'], root / config['model_cache'])
    cache = PairScoreCache(root / config['score_cache'])
    source_files = ['scripts/run_reranking.py', 'src/retrieval/reranking.py']
    identity = {'config': config, 'evidence_policy': dense_config['evidence_match'], 'input_sha256': protected,
                'source_sha256': {p: file_sha256(root / p) for p in source_files}, 'model': scorer.signature}
    run_id = digest(identity)
    output = root / config['output_dir'] / run_id[:16]
    write_json(output / 'experiment.json', dict(identity, run_id=run_id))
    prior_rows = {sy: {r['question_id']: r for kind in ['answerable', 'unanswerable']
                      for r in json.loads((previous / 'sec_section' / sy / (kind + '_results.json')).read_text())}
                  for sy in ['bm25', 'hybrid']}
    results = {f'{sy}_{depth}': [] for sy in config['candidate_sources'] for depth in config['candidate_depths']}
    timing = {'queries': [], 'cache_hits': 0, 'pairs_scored': 0, 'inference_seconds': 0}
    for qi, q in enumerate(questions):
        query_start = time.perf_counter()
        do, ds = cosine_ranking(queries[qi], matrix, ids)
        bo, bs = lexical.rank(q['question'])
        dense_ids, bm25_ids = [ids[i] for i in do], [ids[i] for i in bo]
        hybrid_ids, hs = reciprocal_rank_fusion([dense_ids, bm25_ids], **previous_experiment['config']['rrf'])
        dr, br = ({identifier: i for i, identifier in enumerate(order, 1)} for order in [dense_ids, bm25_ids])
        pools = {}
        for sy, order in [('bm25', bm25_ids), ('hybrid', hybrid_ids)]:
            if order[:10] != [c['chunk_id'] for c in prior_rows[sy][q['question_id']]['results']]:
                raise ValueError('Candidate generator does not reproduce frozen Phase 3C ranks')
            pools[sy] = [{**chunks[position[identifier]], 'rank': rank, 'score_type': sy,
                          'score': float(bs[position[identifier]]) if sy == 'bm25' else hs[identifier],
                          'dense_score': float(ds[position[identifier]]), 'bm25_score': float(bs[position[identifier]]),
                          'rrf_score': hs[identifier], 'dense_rank': dr[identifier], 'bm25_rank': br[identifier],
                          'filing_year': int(chunks[position[identifier]]['filing_date'][:4]),
                          'report_year': int(chunks[position[identifier]]['report_date'][:4])}
                         for rank, identifier in enumerate(order[:max(config['candidate_depths'])], 1)]
        union = {c['chunk_id']: c for pool in pools.values() for c in pool}
        pairs, stats = cache.score(q['question'], [union[key] for key in sorted(union)], scorer)
        timing['cache_hits'] += stats['hits']
        timing['pairs_scored'] += stats['misses']
        timing['inference_seconds'] += stats['inference_seconds']
        for sy, pool in pools.items():
            for depth in config['candidate_depths']:
                ranked = rerank(pool, pairs, depth)
                metrics, matches, analysis = analyze(q, pool[:depth], ranked, dense_config['evidence_match']) if q['answerable'] else (None, [[] for _ in ranked], None)
                for chunk, found in zip(ranked, matches):
                    chunk['matched_evidence_ids'] = found
                row = {'question_id': q['question_id'], 'question': q['question'], 'category': q['category'],
                       'difficulty': q['difficulty'], 'answerable': q['answerable'],
                       'multiple_documents_required': q['multiple_documents_required'],
                       'required_tickers': sorted({d['ticker'] for d in q['required_documents']}),
                       'required_documents': q['required_documents'], 'candidate_depth': depth,
                       'candidate_source': sy, 'metrics': metrics, 'analysis': analysis,
                       'amortized_inference_seconds': sum(pairs[c['chunk_id']]['amortized_inference_seconds'] for c in ranked),
                       'results': ranked}
                results[f'{sy}_{depth}'].append(row)
        timing['queries'].append({'question_id': q['question_id'], 'wall_seconds': time.perf_counter() - query_start,
                                 'unique_pairs': len(union), **stats})
        if qi % 5 == 0 or qi == len(questions) - 1:
            print(f'{qi + 1}/100 questions; {timing["pairs_scored"]} pairs inferred; {timing["inference_seconds"]:.1f}s inference', flush=True)
    summaries = {}
    for key, rows in results.items():
        summary = {'overall': aggregate(rows, [1, 3, 5, 10]), 'by_group': grouped_metrics(rows, [1, 3, 5, 10]),
                   'analysis': summarize_analysis(rows), 'candidate_pairs': sum(len(r['results']) for r in rows),
                   'truncated_pairs': sum(c['reranker_diagnostics']['truncated'] for r in rows for c in r['results']),
                   'estimated_uncached_inference_seconds': sum(r['amortized_inference_seconds'] for r in rows)}
        summary['estimated_uncached_seconds_per_query'] = summary['estimated_uncached_inference_seconds'] / len(rows)
        summaries[key] = summary
        write_json(output / key / 'answerable_results.json', [r for r in rows if r['answerable']])
        write_json(output / key / 'unanswerable_results.json', [r for r in rows if not r['answerable']])
        write_json(output / key / 'summary.json', summary)
    best = sorted(summaries, key=lambda key: (-summaries[key]['overall']['mrr'], -summaries[key]['overall']['recall@5'], key))[0]
    worst = sorted([r for r in results[best] if r['answerable']], key=lambda r: (r['metrics']['recall@10'], r['metrics']['reciprocal_rank'], r['question_id']))[:10]
    write_json(output / 'worst_failures.json', {'configuration': best, 'questions': worst})
    baseline = json.loads((previous / 'summary.json').read_text())['strategies']['sec_section']
    write_json(output / 'summary.json', {'run_id': run_id, 'baselines': baseline, 'reranked': summaries,
                                       'best_descriptive_configuration_by_mrr': best, 'prior_inputs_unchanged': True})
    if any(file_sha256(root / path) != value for path, value in protected.items()):
        raise ValueError('Protected artifacts changed during reranking')
    timing['model_load_seconds'] = scorer.load_seconds
    timing['total_wall_seconds'] = time.perf_counter() - start
    timing['average_query_wall_seconds'] = sum(q['wall_seconds'] for q in timing['queries']) / len(questions)
    timing['average_inference_seconds_per_query'] = timing['inference_seconds'] / len(questions)
    write_json(output / 'executions' / (str(time.time_ns()) + '.json'), timing)
    print('Complete experiment:', output, flush=True)
    print(json.dumps({k: v for k, v in timing.items() if k != 'queries'}), flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description='Local cross-encoder candidate reranking')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--config', type=Path, default=Path('configs/reranking.json'))
    args = parser.parse_args()
    root = args.root.resolve()
    run_experiment(root, json.loads((root / args.config).read_text()))


if __name__ == '__main__':
    main()
