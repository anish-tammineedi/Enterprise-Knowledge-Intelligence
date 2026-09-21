from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

import numpy as np

from scripts.run_dense_retrieval import FROZEN_BENCHMARK_SHA256, load_chunks, verify_frozen_benchmark
from src.embeddings.local_dense import EmbeddingCache, digest
from src.evaluation.dense_metrics import aggregate, evaluate_question, grouped_metrics, match_evidence, union_fraction
from src.retrieval.dense import cosine_ranking


ROOT = Path(__file__).resolve().parents[1]
POLICY = {'minimum_evidence_fraction': 0.5, 'minimum_nonwhitespace_characters': 32, 'strict_union_fraction': 0.95}
KS = [1, 3, 5, 10]


class FakeEncoder:
    def __init__(self, revision='one'):
        self.signature = {'revision': revision, 'batch_size': 2}
        self.dimensions = 3
        self.calls = []

    def encode(self, texts, role):
        self.calls.extend((text, role) for text in texts)
        vectors = np.array([[len(text) + 1, sum(map(ord, text)) % 101 + 1, 2] for text in texts], dtype=np.float32)
        return vectors, [{'token_count': len(t), 'truncated': False, 'encoded_text_end_char': len(t)} for t in texts]


def evidence(document='A', identifier='E1'):
    return {'evidence_id': identifier, 'document_id': document, 'accession_number': document + '-acc',
            'ticker': document, 'company': document + ' Company', 'source_url': 'https://example.com/' + document,
            'section_id': document + ':1', 'item': '1', 'start_char': 0, 'end_char': 100, 'text': 'x' * 100}


def chunk(source, start=0, end=100):
    return {**source, 'chunk_id': f"{source['document_id']}-{start}-{end}",
            'start_char': start, 'end_char': end, 'text': source['text'][start:end],
            'sections': [{'section_id': source['section_id']}]}


def question():
    return {'answerable': True, 'evidence': [evidence(), evidence('B', 'E2')],
            'multiple_documents_required': True, 'required_documents': [{'document_id': 'A'}, {'document_id': 'B'}]}


class DenseRetrievalTests(unittest.TestCase):
    def test_cache_reuse_changes_and_alignment(self):
        records = [{'id': 'second', 'text': 'bravo'}, {'id': 'first', 'text': 'alpha'}]
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            cache = EmbeddingCache(directory)
            encoder = FakeEncoder()
            vectors, details, stats = cache.encode(records, encoder, 'fixed_size')
            self.assertEqual(stats, {'hits': 0, 'misses': 2})
            before = {p: p.stat().st_mtime_ns for p in Path(directory).rglob('*') if p.is_file()}
            reversed_vectors, _, stats = cache.encode(list(reversed(records)), encoder, 'fixed_size')
            np.testing.assert_array_equal(reversed_vectors, vectors[::-1])
            self.assertEqual(stats, {'hits': 2, 'misses': 0})
            self.assertEqual(len(encoder.calls), 2)
            self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})
            changed = deepcopy(records)
            changed[0]['text'] = 'changed'
            _, _, stats = cache.encode(changed, encoder, 'fixed_size')
            self.assertEqual(stats, {'hits': 1, 'misses': 1})
            _, _, stats = cache.encode(records, FakeEncoder('two'), 'fixed_size')
            self.assertEqual(stats['misses'], 2)
            _, _, stats = cache.encode(records, encoder, 'fixed_size', 'query')
            self.assertEqual(stats['misses'], 2)
            _, _, stats = cache.encode(records, encoder, 'recursive')
            self.assertEqual(stats['misses'], 2)

    def test_cache_corruption_is_recomputed(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            encoder = FakeEncoder()
            cache = EmbeddingCache(directory)
            records = [{'id': 'one', 'text': 'text'}]
            original, _, _ = cache.encode(records, encoder, 'test')
            next(Path(directory).rglob('*.npy')).write_bytes(b'broken')
            repaired, _, stats = cache.encode(records, encoder, 'test')
            np.testing.assert_array_equal(original, repaired)
            self.assertEqual(stats['misses'], 1)
            with self.assertRaises(ValueError):
                cache.encode(records * 2, encoder, 'test')

    def test_cosine_ranking_and_ties(self):
        matrix = np.array([[0, 2], [3, 0], [1, 0], [-1, 0]])
        order, scores = cosine_ranking(np.array([2, 0]), matrix, ['d', 'b', 'a', 'c'])
        self.assertEqual(order.tolist(), [2, 1, 0, 3])
        np.testing.assert_allclose(scores, [0, 1, 1, -1])
        with self.assertRaises(ValueError):
            cosine_ranking(np.array([0, 0]), matrix, ['d', 'b', 'a', 'c'])
        with self.assertRaises(ValueError):
            cosine_ranking(np.array([1, 0]), matrix, ['a'] * 4)

    def test_evidence_requires_provenance_text_and_substantial_overlap(self):
        e = evidence()
        self.assertTrue(match_evidence(chunk(e, 0, 50), e, POLICY))
        self.assertFalse(match_evidence(chunk(e, 80, 100), e, POLICY))
        for key, value in [('document_id', 'B'), ('accession_number', 'bad'), ('ticker', 'B'),
                           ('company', 'wrong'), ('source_url', 'wrong'), ('text', 'y' * 100), ('sections', [])]:
            c = chunk(e)
            c[key] = value
            with self.subTest(field=key):
                self.assertFalse(match_evidence(c, e, POLICY))
        e['text'] = ' ' * 100
        self.assertFalse(match_evidence(chunk(e), e, POLICY))
        short = {**evidence(), 'end_char': 5, 'text': 'None.'}
        self.assertTrue(match_evidence(chunk(short, 0, 5), short, POLICY))

    def test_union_deduplicates_overlapping_characters(self):
        e = evidence()
        chunks = [chunk(e, 0, 40), chunk(e, 20, 60), chunk(e, 60, 100)]
        self.assertEqual(union_fraction(chunks, e), 1)
        self.assertFalse(any(match_evidence(c, e, POLICY) for c in chunks))
        self.assertEqual(union_fraction([chunks[0], chunks[0]], e), 0.4)

    def test_metrics_and_multidocument_recovery(self):
        q = question()
        ranked = [chunk(evidence('C')), chunk(q['evidence'][0]), chunk(q['evidence'][0]), chunk(q['evidence'][1])]
        metrics, matches = evaluate_question(q, ranked, KS, POLICY)
        self.assertEqual(metrics['reciprocal_rank'], 0.5)
        self.assertEqual(metrics['recall@1'], 0)
        self.assertEqual(metrics['recall@3'], 0.5)
        self.assertEqual(metrics['recall@5'], 1)
        self.assertEqual(metrics['hit_rate@3'], 1)
        self.assertEqual(metrics['multi_document_complete_recall@3'], 0)
        self.assertEqual(metrics['multi_document_complete_recall@5'], 1)
        self.assertEqual(metrics['complete_evidence@3'], 0)
        self.assertEqual(metrics['first_relevant_rank'], 2)
        self.assertEqual(matches[0], [])
        wrong_filing = chunk(evidence('B'))
        wrong_filing['text'] = 'wrong'
        metrics, _ = evaluate_question(q, [ranked[1], wrong_filing], KS, POLICY)
        self.assertEqual(metrics['multi_document_complete_recall@10'], 0)

    def test_full_ranking_mrr_and_unanswerable_exclusion(self):
        q = question()
        metrics, _ = evaluate_question(q, [chunk(evidence('C'))] * 11 + [chunk(evidence())], KS, POLICY)
        self.assertEqual(metrics['reciprocal_rank'], 1 / 12)
        self.assertEqual(metrics['hit_rate@10'], 0)
        negative = {'answerable': False, 'multiple_documents_required': False}
        self.assertIsNone(evaluate_question(negative, [], KS, POLICY))
        row = {**q, 'metrics': metrics, 'category': 'cross_document', 'difficulty': 'hard', 'required_tickers': ['A', 'B']}
        summary = aggregate([row, negative], KS)
        self.assertEqual(summary['answerable_questions'], 1)
        self.assertEqual(summary['mrr'], 1 / 12)
        groups = grouped_metrics([row, negative], KS)
        self.assertEqual(groups['ticker']['B']['answerable_questions'], 1)
        self.assertIsNone(aggregate([negative], KS)['mrr'])

    def test_frozen_benchmark_and_existing_chunk_alignment(self):
        if not list((ROOT / 'data/processed/parsed').glob('*.json')):
            self.skipTest('Parsed SEC corpus is not prepared')
        benchmark_path = ROOT / 'evals/ground_truth/sec_retrieval_benchmark.json'
        before = benchmark_path.read_bytes()
        verify_frozen_benchmark(benchmark_path)
        self.assertEqual(hashlib.sha256(before).hexdigest(), FROZEN_BENCHMARK_SHA256)
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / 'benchmark.json'
            altered.write_bytes(before + b' ')
            with self.assertRaises(ValueError):
                verify_frozen_benchmark(altered)
        docs = {}
        for p in (ROOT / 'data/processed/parsed').glob('*.json'):
            doc = json.loads(p.read_text())
            docs[doc['document_id']] = doc
        config = json.loads((ROOT / 'configs/dense_retrieval.json').read_text())
        for strategy, directory in config['chunk_dirs'].items():
            chunks, _ = load_chunks(ROOT / directory, strategy, docs)
            self.assertEqual(len(chunks), len({c['chunk_id'] for c in chunks}))
            self.assertEqual(chunks, sorted(chunks, key=lambda c: (c['document_id'], c['chunk_index'], c['chunk_id'])))
        self.assertEqual(before, benchmark_path.read_bytes())


if __name__ == '__main__':
    unittest.main()
