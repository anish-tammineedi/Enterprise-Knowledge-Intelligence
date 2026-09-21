import unittest
import hashlib
import json
from pathlib import Path

from src.evaluation.generation_metrics import aggregate_generation, evaluate_trace, select_subset
from src.generation.grounding import ABSTENTION


def context(text='Revenue was $100 million.', cid='C001'):
    return {'context_id': cid, 'chunk_id': 'chunk-a', 'document_id': 'doc-a', 'source_document_id': 'doc-a',
            'company': 'Example', 'ticker': 'EX', 'cik': '1', 'form': '10-K', 'filing_date': '2025-10-31',
            'report_date': '2025-09-30', 'accession_number': '0001', 'item': '7', 'section_id': 'doc-a:7',
            'section_name': 'MD&A', 'sections': [{'section_id': 'doc-a:7'}], 'source_url': 'https://sec.example',
            'start_char': 0, 'end_char': len(text), 'text': text}


class GenerationEvaluationTests(unittest.TestCase):
    def question(self, answerable=True):
        return {'question_id': 'Q', 'answerable': answerable, 'expected_answer': 'Revenue was $100 million.',
                'evidence': [{'evidence_id': 'E1', 'document_id': 'doc-a', 'accession_number': '0001',
                              'ticker': 'EX', 'company': 'Example', 'source_url': 'https://sec.example',
                              'section_id': 'doc-a:7', 'item': '7', 'section_name': 'MD&A', 'start_char': 0,
                              'end_char': 26, 'text': 'Revenue was $100 million.'}]}

    def trace(self, output, status='success', citations=None, abstained=False):
        return {'status': status, 'contexts': [context()], 'parsed_answer': output,
                'citations': citations or [], 'abstained': abstained, 'latency_seconds': 1,
                'token_usage': {'input_tokens': 2, 'output_tokens': 3, 'total_tokens': 5}}

    def test_grounded_correct_and_metrics(self):
        r = evaluate_trace(self.question(), self.trace({'answer': 'Revenue was $100 million [C001].',
            'citations': ['C001'], 'abstained': False}, citations=['C001']), {'minimum_nonwhitespace_characters': 1, 'minimum_evidence_fraction': 0.0})
        self.assertEqual(r['attribution'], 'successful_grounded_answer')
        self.assertEqual(r['citation_precision'], 1.0)

    def test_retrieval_miss_and_false_abstention(self):
        q = self.question()
        q['evidence'][0]['document_id'] = 'other'
        r = evaluate_trace(q, self.trace({'answer': ABSTENTION, 'citations': [], 'abstained': True}, abstained=True), {'minimum_nonwhitespace_characters': 1, 'minimum_evidence_fraction': 0.0})
        self.assertEqual(r['attribution'], 'retrieval_failure')
        r = evaluate_trace(self.question(), self.trace({'answer': ABSTENTION, 'citations': [], 'abstained': True}, abstained=True), {'minimum_nonwhitespace_characters': 1, 'minimum_evidence_fraction': 0.0})
        self.assertEqual(r['attribution'], 'generation_failure')

    def test_unanswerable_and_invalid_output(self):
        r = evaluate_trace(self.question(False), self.trace({'answer': ABSTENTION, 'citations': [], 'abstained': True}, abstained=True), {'minimum_nonwhitespace_characters': 1, 'minimum_evidence_fraction': 0.0})
        self.assertEqual(r['attribution'], 'expected_abstention')
        r = evaluate_trace(self.question(), self.trace(None, status='invalid_output'), {'minimum_nonwhitespace_characters': 1, 'minimum_evidence_fraction': 0.0})
        self.assertEqual(r['attribution'], 'invalid_structured_output')

    def test_hallucinated_and_missing_citation(self):
        r = evaluate_trace(self.question(), self.trace({'answer': 'Other fact [C999].', 'citations': ['C999'], 'abstained': False}, citations=['C999']), {'minimum_nonwhitespace_characters': 1, 'minimum_evidence_fraction': 0.0})
        self.assertEqual(r['attribution'], 'citation_failure')
        r = evaluate_trace(self.question(), self.trace({'answer': 'Revenue was $100 million.', 'citations': [], 'abstained': False}, status='invalid_output'), {'minimum_nonwhitespace_characters': 1, 'minimum_evidence_fraction': 0.0})
        self.assertEqual(r['attribution'], 'invalid_structured_output')

    def test_aggregate_and_subset(self):
        rows = [{'answerable': True, 'status': 'success', 'abstained': False, 'expected_abstention': False, 'citation_validity': True, 'citation_precision': 1, 'citation_recall': 1, 'groundedness_heuristic': True, 'latency_seconds': 1, 'token_usage': {'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 3}}, {'answerable': False, 'status': 'success', 'abstained': True, 'expected_abstention': True, 'citation_validity': True, 'citation_precision': None, 'citation_recall': None, 'groundedness_heuristic': None, 'latency_seconds': 2, 'token_usage': {'input_tokens': 2, 'output_tokens': 1, 'total_tokens': 3}}]
        self.assertEqual(aggregate_generation(rows)['unanswerable_abstention_rate'], 1.0)
        qs = [{'question_id': f'SEC-{i:03}', 'category': c, 'difficulty': d} for i, (c, d) in enumerate([('direct_factual', 'easy'), ('direct_factual', 'easy'), ('numerical', 'easy'), ('numerical', 'hard')], 1)]
        self.assertEqual(len(select_subset(qs)), 4)

    def test_frozen_benchmark_hash(self):
        root = Path(__file__).resolve().parents[1]
        benchmark = root / 'evals/ground_truth/sec_retrieval_benchmark.json'
        manifest = json.loads((root / 'configs/generation_protected.json').read_text())
        self.assertEqual(hashlib.sha256(benchmark.read_bytes()).hexdigest(), manifest['sha256'][str(benchmark.relative_to(root))])


if __name__ == '__main__':
    unittest.main()
