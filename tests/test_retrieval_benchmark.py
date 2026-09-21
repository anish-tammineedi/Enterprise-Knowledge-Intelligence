from copy import deepcopy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from scripts.validate_retrieval_benchmark import main, validate_benchmark, validate_question


ROOT = Path(__file__).resolve().parents[1]


class RetrievalBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parsed = list((ROOT / 'data/processed/parsed').glob('*.json'))
        if len(parsed) != 9:
            raise unittest.SkipTest('The nine-filing parsed corpus is not prepared')
        cls.benchmark = json.loads((ROOT / 'evals/ground_truth/sec_retrieval_benchmark.json').read_text())
        cls.documents = {}
        for path in parsed:
            doc = json.loads(path.read_text())
            cls.documents[doc['document_id']] = doc

    def test_complete_benchmark(self):
        result = validate_benchmark(self.benchmark, ROOT)
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['question_count'], 100)
        self.assertEqual(result['answerable_count'], 90)
        self.assertEqual(result['unanswerable_count'], 10)
        self.assertEqual(result['single_document_count'], 69)
        self.assertEqual(result['multi_document_count'], 21)
        self.assertEqual(set(result['category_counts'].values()), {10})
        self.assertEqual(len(result['questions_per_document']), 9)

    def test_duplicate_id_and_question(self):
        for field in ('question_id', 'question'):
            benchmark = deepcopy(self.benchmark)
            benchmark['questions'][1][field] = benchmark['questions'][0][field]
            result = validate_benchmark(benchmark, ROOT)
            self.assertFalse(result['valid'])
            self.assertTrue(any('Duplicate question' in error for error in result['errors']))

    def test_bad_evidence_and_offsets(self):
        for field, value in [('text', 'Invented evidence'), ('start_char', -1),
                             ('end_char', 99999999), ('item', '99'),
                             ('section_name', 'Wrong section'), ('contains_table', True),
                             ('content_block_indices', [9999999])]:
            question = deepcopy(self.benchmark['questions'][0])
            question['evidence'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_question(question, self.documents)

    def test_incorrect_metadata_and_document_references(self):
        for field, value in [('company', 'Other Company'), ('ticker', 'NVDA'),
                             ('cik', '9999999999'), ('accession_number', 'invalid'),
                             ('document_id', 'unknown'), ('report_year', 1900),
                             ('filing_year', 1900), ('source_url', 'https://example.com')]:
            question = deepcopy(self.benchmark['questions'][0])
            question['required_documents'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_question(question, self.documents)

    def test_labels_and_required_evidence(self):
        for field, value in [('answerable', 'yes'), ('expected_answer', None),
                             ('evidence', []), ('required_documents', []),
                             ('multiple_documents_required', True)]:
            question = deepcopy(self.benchmark['questions'][0])
            question[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_question(question, self.documents)
        question = deepcopy(self.benchmark['questions'][40])
        question['multiple_documents_required'] = False
        with self.assertRaises(ValueError):
            validate_question(question, self.documents)

    def test_unanswerable_justifications(self):
        for field, value in [('unanswerable_reason', ''), ('expected_answer', 'Invented number'),
                             ('absence_audit', None), ('answerable', True)]:
            question = deepcopy(self.benchmark['questions'][80])
            question[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_question(question, self.documents)
        question = deepcopy(self.benchmark['questions'][80])
        question['query_scope']['tickers'] = ['INVALID']
        with self.assertRaises(ValueError):
            validate_question(question, self.documents)

    def test_distribution_and_manifest_drift(self):
        benchmark = deepcopy(self.benchmark)
        benchmark['questions'][0]['category'] = 'section_specific'
        result = validate_benchmark(benchmark, ROOT)
        self.assertFalse(result['valid'])
        self.assertIn('Category distribution', result['errors'][0])
        benchmark = deepcopy(self.benchmark)
        benchmark['corpus'][0]['text_sha256'] = '0' * 64
        result = validate_benchmark(benchmark, ROOT)
        self.assertFalse(result['valid'])
        self.assertIn('Corpus text changed', result['errors'][0])

    def test_missing_required_fields_and_malformed_structure(self):
        for field in ('difficulty', 'acceptable_answer_variants', 'required_documents', 'query_scope'):
            benchmark = deepcopy(self.benchmark)
            del benchmark['questions'][0][field]
            self.assertFalse(validate_benchmark(benchmark, ROOT)['valid'])
        benchmark = deepcopy(self.benchmark)
        benchmark['questions'][0] = None
        self.assertFalse(validate_benchmark(benchmark, ROOT)['valid'])
        self.assertFalse(validate_benchmark([], ROOT)['valid'])

    def test_table_and_multidocument_category_requirements(self):
        for category in ('table_oriented', 'cross_document', 'comparative', 'multi_hop'):
            question = deepcopy(self.benchmark['questions'][0])
            question['category'] = category
            with self.subTest(category=category), self.assertRaises(ValueError):
                validate_question(question, self.documents)

    def test_answer_leakage_guard(self):
        question = deepcopy(self.benchmark['questions'][0])
        question['question'] += ' ' + question['expected_answer']
        with self.assertRaisesRegex(ValueError, 'appears in question'):
            validate_question(question, self.documents)

    def test_cli_and_report_idempotency(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            report = Path(directory) / 'report.json'
            args = ['--report', str(report)]
            self.assertEqual(main(args), 0)
            before = report.read_bytes(), report.stat().st_mtime_ns
            self.assertEqual(main(args), 0)
            self.assertEqual(before, (report.read_bytes(), report.stat().st_mtime_ns))
            invalid = Path(directory) / 'invalid.json'
            invalid.write_text(json.dumps({'schema_version': 'unknown'}))
            self.assertEqual(main(['--benchmark', str(invalid)]), 1)


if __name__ == '__main__':
    unittest.main()
