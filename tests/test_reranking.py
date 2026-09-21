from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.run_dense_retrieval import verify_frozen_benchmark
from scripts.run_reranking import summarize_analysis
from src.retrieval.reranking import PairScoreCache, analyze, rerank


POLICY = {'minimum_evidence_fraction': .5, 'minimum_nonwhitespace_characters': 32, 'strict_union_fraction': .95}


def evidence(identifier, document):
    return {'evidence_id': identifier, 'document_id': document, 'accession_number': document,
            'ticker': document, 'company': document, 'source_url': 'https://example.com/' + document,
            'section_id': document + ':1', 'text': 'x' * 100, 'start_char': 0, 'end_char': 100}


def candidate(e, identifier, rank):
    return {**e, 'chunk_id': identifier, 'rank': rank, 'score_type': 'bm25', 'score': 1,
            'sections': [{'section_id': e['section_id']}]}


class FakeScorer:
    signature = {'revision': 'fake', 'batch_size': 2}

    def __init__(self):
        self.calls = 0

    def score(self, pairs):
        self.calls += len(pairs)
        return np.array([len(text) for _, text in pairs]), [{'truncated': False} for _ in pairs], .1


class RerankingTests(unittest.TestCase):
    def test_order_depth_and_provenance(self):
        e = evidence('E1', 'A')
        candidates = [candidate(e, 'b', 1), candidate(e, 'a', 2), candidate(e, 'c', 3)]
        scores = {c['chunk_id']: {'score': 2 if c['chunk_id'] == 'c' else 1, 'diagnostics': {}} for c in candidates}
        before = deepcopy(candidates)
        ranked = rerank(candidates, scores, 2)
        self.assertEqual([c['chunk_id'] for c in ranked], ['a', 'b'])
        self.assertEqual([c['rank'] for c in ranked], [1, 2])
        self.assertEqual(ranked[0]['original_retrieval_rank'], 2)
        self.assertEqual(ranked[0]['original_retrieval_system'], 'bm25')
        for key in ['company', 'ticker', 'accession_number', 'source_url', 'text', 'sections', 'start_char', 'end_char']:
            self.assertEqual(ranked[0][key], candidates[1][key])
        self.assertEqual(candidates, before)
        self.assertEqual(ranked, rerank(candidates, scores, 2))
        self.assertEqual(rerank(candidates, scores, 3)[0]['chunk_id'], 'c')
        with self.assertRaises(ValueError):
            rerank(candidates, {}, 2)
        with self.assertRaises(ValueError):
            rerank(candidates, scores, 0)
        scores['a']['score'] = float('nan')
        with self.assertRaises(ValueError):
            rerank(candidates, scores, 2)

    def test_pair_cache_alignment_invalidation_and_corruption(self):
        scorer = FakeScorer()
        chunks = [{'chunk_id': 'a', 'text': 'one'}, {'chunk_id': 'b', 'text': 'longer'}]
        with tempfile.TemporaryDirectory() as directory:
            cache = PairScoreCache(directory)
            first, stats = cache.score('query', chunks, scorer)
            self.assertEqual(stats['misses'], 2)
            second, stats = cache.score('query', chunks[::-1], scorer)
            self.assertEqual(stats['hits'], 2)
            self.assertEqual(first, second)
            self.assertEqual(first['a']['score'], 3)
            self.assertEqual(first['b']['score'], 6)
            self.assertEqual(scorer.calls, 2)
            _, stats = cache.score('different query', chunks, scorer)
            self.assertEqual(stats['misses'], 2)
            changed = deepcopy(chunks)
            changed[0]['text'] = 'changed'
            _, stats = cache.score('query', changed, scorer)
            self.assertEqual(stats['misses'], 1)
            for path in Path(directory).rglob('*.json'):
                entry = json.loads(path.read_text())
                if entry['identity']['question'] == 'query' and entry['identity']['chunk_id'] == 'b':
                    entry['score'] = 999
                    path.write_text(json.dumps(entry))
            _, stats = cache.score('query', chunks, scorer)
            self.assertEqual(stats['misses'], 1)

    def test_failure_classification_metrics_and_movement(self):
        a, b, wrong = evidence('E1', 'A'), evidence('E2', 'B'), evidence('E3', 'C')
        q = {'answerable': True, 'evidence': [a, b], 'required_documents': [{'document_id': 'A'}, {'document_id': 'B'}], 'multiple_documents_required': True}
        pool = [candidate(wrong, str(i), i + 1) for i in range(10)] + [candidate(a, 'a', 11)]
        scores = {c['chunk_id']: {'score': int(c['chunk_id'] == 'a'), 'diagnostics': {}} for c in pool}
        ranked = rerank(pool, scores, 11)
        metrics, _, analysis = analyze(q, pool, ranked, POLICY)
        self.assertEqual(metrics['reciprocal_rank'], 1)
        self.assertEqual(metrics['recall@1'], .5)
        self.assertEqual(analysis['oracle_evidence_recall'], .5)
        self.assertEqual(analysis['missing_from_pool'], ['E2'])
        self.assertEqual(analysis['failure_class'], 'candidate_generation')
        self.assertEqual(analysis['movement']['promoted_into_top1'], ['a'])
        _, _, before = analyze(q, pool, pool, POLICY)
        self.assertEqual(before['failure_class'], 'both')
        pool.append(candidate(b, 'b', 12))
        _, _, failure = analyze(q, pool, pool, POLICY)
        self.assertEqual(failure['failure_class'], 'reranking')
        promoted = [pool[-1], pool[-2], *pool[:-2]]
        metrics, _, success = analyze(q, pool, promoted, POLICY)
        self.assertEqual(success['failure_class'], 'complete')
        self.assertEqual(metrics['multi_document_complete_recall@3'], 1)
        _, _, demotion = analyze(q, promoted, pool, POLICY)
        self.assertEqual(set(demotion['movement']['demoted_out_of_top5']), {'a', 'b'})
        row = {'question_id': 'test', 'answerable': True, 'multiple_documents_required': True, 'analysis': success}
        summary = summarize_analysis([row, {'answerable': False}])
        self.assertEqual(summary['oracle_all_evidence'], 1)
        self.assertEqual(summary['questions_by_recall_change']['5']['improved'], ['test'])

    def test_benchmark_immutable(self):
        root = Path(__file__).resolve().parents[1]
        path = root / 'evals/ground_truth/sec_retrieval_benchmark.json'
        before = path.read_bytes()
        verify_frozen_benchmark(path)
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / 'benchmark.json'
            copy.write_bytes(before + b' ')
            with self.assertRaises(ValueError):
                verify_frozen_benchmark(copy)
        self.assertEqual(before, path.read_bytes())


if __name__ == '__main__':
    unittest.main()
