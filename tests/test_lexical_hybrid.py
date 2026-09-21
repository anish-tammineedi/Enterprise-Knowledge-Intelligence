from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.run_dense_retrieval import verify_frozen_benchmark
from scripts.run_lexical_hybrid import complementarity
from src.evaluation.dense_metrics import evaluate_question, match_evidence
from src.retrieval.lexical import BM25, reciprocal_rank_fusion, tokenize


class LexicalHybridTests(unittest.TestCase):
    def test_financial_tokenization(self):
        text = "Apple NVIDIA Microsoft 10-K Item 1A FY2026 $133,749 71.1% non-GAAP iPhone U.S. CUDA"
        expected = ['apple', 'nvidia', 'microsoft', '10-k', 'item', '1a', 'fy2026', '133749', '71.1%', 'non-gaap', 'iphone', 'u.s', 'cuda']
        self.assertEqual(tokenize(text), expected)
        self.assertEqual(tokenize(text), tokenize(text))
        self.assertEqual(tokenize('NON‑GAAP ２０２６ NVIDIA’s'), ['non-gaap', '2026', "nvidia's"])
        self.assertEqual(tokenize('133749 133,749 2025 2026'), ['133749', '133749', '2025', '2026'])
        self.assertEqual(tokenize(''), [])

    def test_bm25_formula_and_ranking(self):
        index = BM25(['revenue revenue', 'revenue', 'cloud'], ['a', 'b', 'c'], k1=1.2, b=0.75)
        order, scores = index.rank('revenue')
        idf = math.log1p(1.5 / 2.5)
        self.assertAlmostEqual(scores[0], idf * 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 2 / (4 / 3))))
        self.assertEqual(order.tolist(), [0, 1, 2])
        self.assertEqual(scores[2], 0)
        np.testing.assert_array_equal(scores, index.rank('revenue revenue')[1])
        index = BM25(['Microsoft 2025 revenue', 'Microsoft 2026 revenue', 'Apple 2026 revenue'], ['a', 'b', 'c'])
        self.assertEqual(index.rank('Microsoft 2026')[0][0], 1)

    def test_bm25_ties_empty_and_invalid(self):
        index = BM25(['', ''], ['b', 'a'])
        self.assertEqual(index.rank('unknown')[0].tolist(), [1, 0])
        np.testing.assert_array_equal(index.rank('')[1], [0, 0])
        for args in [([], []), (['x'], ['a', 'b']), (['x', 'y'], ['a', 'a'])]:
            with self.assertRaises(ValueError):
                BM25(*args)
        for k1, b in [(0, .75), (1.2, 2), (float('nan'), .75)]:
            with self.assertRaises(ValueError):
                BM25(['x'], ['a'], k1, b)

    def test_rrf_arithmetic_determinism_and_depth(self):
        ranks = [['a', 'b', 'c'], ['b', 'c', 'a']]
        order, scores = reciprocal_rank_fusion(ranks, 60)
        self.assertEqual(order, ['b', 'a', 'c'])
        self.assertAlmostEqual(scores['b'], 1 / 62 + 1 / 61)
        self.assertEqual((order, scores), reciprocal_rank_fusion(ranks[::-1], 60))
        tied, _ = reciprocal_rank_fusion([['b', 'a'], ['a', 'b']], 0)
        self.assertEqual(tied, ['a', 'b'])
        limited, scores = reciprocal_rank_fusion(ranks, 60, 1)
        self.assertEqual(limited, ['a', 'b'])
        self.assertEqual(scores['a'], 1 / 61)
        full, _ = reciprocal_rank_fusion([[str(i) for i in range(200)]], candidate_depth=None)
        self.assertEqual(len(full), 200)
        for rankings, constant, depth in [([['a', 'a']], 60, None), (ranks, -1, None), (ranks, 60, 0)]:
            with self.assertRaises(ValueError):
                reciprocal_rank_fusion(rankings, constant, depth)

    def test_frozen_evidence_and_metrics_reused(self):
        root = Path(__file__).resolve().parents[1]
        path = root / 'evals/ground_truth/sec_retrieval_benchmark.json'
        before = path.read_bytes()
        verify_frozen_benchmark(path)
        q = next(q for q in json.loads(before)['questions'] if q['answerable'])
        e = q['evidence'][0]
        c = {**e, 'sections': [{'section_id': e['section_id']}]}
        policy = json.loads((root / 'configs/dense_retrieval.json').read_text())['evidence_match']
        self.assertTrue(match_evidence(c, e, policy))
        wrong = {**c, 'accession_number': 'incorrect'}
        self.assertFalse(match_evidence(wrong, e, policy))
        metrics, _ = evaluate_question(q, [wrong, c], [1, 3, 5, 10], policy)
        self.assertEqual(metrics['reciprocal_rank'], .5)
        self.assertEqual(metrics['hit_rate@1'], 0)
        self.assertEqual(metrics['hit_rate@3'], 1)
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / 'benchmark.json'
            altered.write_bytes(before + b' ')
            with self.assertRaises(ValueError):
                verify_frozen_benchmark(altered)
        self.assertEqual(path.read_bytes(), before)

    def test_complementarity_uses_complete_evidence(self):
        systems = {s: [] for s in ['dense', 'bm25', 'hybrid']}
        values = {'one': [1, 0, .5], 'two': [0, 1, 1], 'three': [.5, .5, 1], 'four': [0, 0, 0]}
        for qid, recalls in values.items():
            for s, recall in zip(systems, recalls):
                systems[s].append({'question_id': qid, 'answerable': True,
                                   'metrics': {'recall@10': recall, 'recovered_evidence@10': ['E'] if recall else []}})
        result = complementarity(deepcopy(systems))['groups']
        self.assertEqual(result['dense_not_bm25']['question_ids'], ['one'])
        self.assertEqual(result['bm25_not_dense']['question_ids'], ['two'])
        self.assertEqual(result['hybrid_only']['question_ids'], ['three'])
        self.assertEqual(result['missed_by_all']['question_ids'], ['four'])
        self.assertEqual(result['standalone_solved_hybrid_missed']['question_ids'], ['one'])


if __name__ == '__main__':
    unittest.main()
