from dataclasses import replace
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest

from scripts.chunk_sec_filings import main
from src.ingestion.chunking import (
    ChunkingConfig, STRATEGIES, chunk_document, generate_experiment, summarize,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ChunkingConfig('fixed_size', 100, 20, 30, 0.5)


def document(parts=None, document_id='EX_001', preamble='Cover page.\n\n'):
    parts = parts if parts is not None else [('1', 'Business', 'A business sentence. ' * 30),
                                             ('1A', 'Risk Factors', 'A risk sentence. ' * 30)]
    text = preamble
    sections = []
    content = []
    for item, name, body in parts:
        start = len(text)
        value = f'Item {item}. {name}\n\n{body}'
        text += value
        sections.append({'section_id': f'{document_id}:item_{item}', 'item': item, 'name': name,
                         'text': value, 'start_char': start, 'end_char': len(text)})
        content.append({'type': 'paragraph', 'text': value, 'start_char': start, 'end_char': len(text)})
        text += '\n\n'
    return {'company': 'Example Company', 'ticker': 'EX', 'cik': '0000000001', 'form': '10-K',
            'filing_date': '2025-02-01', 'report_date': '2024-12-31', 'accession_number': document_id,
            'source_url': f'https://www.sec.gov/Archives/{document_id}.htm',
            'document_id': document_id, 'local_path': f'data/raw/{document_id}.html',
            'source_sha256': 'a' * 64, 'text': text, 'sections': sections, 'content': content}


def plain_document(text):
    result = document(parts=[], preamble=text)
    result['content'] = [{'type': 'paragraph', 'text': text, 'start_char': 0, 'end_char': len(text)}] if text else []
    return result


def assert_coverage(case, source, chunks):
    cursor = 0
    for chunk in chunks:
        start, end = chunk['start_char'], chunk['end_char']
        case.assertEqual(chunk['text'], source['text'][start:end])
        case.assertFalse(source['text'][cursor:start].strip())
        cursor = max(cursor, end)
    case.assertFalse(source['text'][cursor:].strip())


class ChunkingTests(unittest.TestCase):
    def test_deterministic_ids_and_config_identity(self):
        source = document()
        for strategy in STRATEGIES:
            config = replace(CONFIG, strategy=strategy)
            chunks = chunk_document(source, config)
            self.assertEqual(chunks, chunk_document(source, config))
            self.assertEqual(len(chunks), len({chunk['chunk_id'] for chunk in chunks}))
            changed = chunk_document(source, replace(config, overlap=10))
            self.assertTrue({c['chunk_id'] for c in chunks}.isdisjoint(c['chunk_id'] for c in changed))
        changed_source = document(document_id='EX_002')
        self.assertNotEqual(chunk_document(source, CONFIG)[0]['chunk_id'],
                            chunk_document(changed_source, CONFIG)[0]['chunk_id'])

    def test_provenance(self):
        source = document()
        for strategy in STRATEGIES:
            for index, chunk in enumerate(chunk_document(source, replace(CONFIG, strategy=strategy))):
                for key in ('company', 'ticker', 'cik', 'form', 'filing_date', 'report_date',
                            'accession_number', 'source_url', 'local_path', 'source_sha256'):
                    self.assertEqual(chunk[key], source[key])
                self.assertEqual(chunk['source_document_id'], source['document_id'])
                self.assertEqual(chunk['chunk_index'], index)
                self.assertEqual(chunk['text'], source['text'][chunk['start_char']:chunk['end_char']])

    def test_section_boundaries_oversized_and_small_sections(self):
        source = document(parts=[('1', 'Business', 'Long business. ' * 100), ('6', 'Reserved', 'None.')])
        chunks = chunk_document(source, replace(CONFIG, strategy='sec_section'))
        by_id = {s['section_id']: s for s in source['sections']}
        self.assertGreater(sum(c['item'] == '1' for c in chunks), 1)
        reserved = [c for c in chunks if c['item'] == '6']
        self.assertEqual(len(reserved), 1)
        self.assertEqual(reserved[0]['text'], source['sections'][1]['text'])
        for chunk in chunks:
            self.assertLessEqual(len(chunk['sections']), 1)
            if chunk['section_id']:
                section = by_id[chunk['section_id']]
                self.assertGreaterEqual(chunk['start_char'], section['start_char'])
                self.assertLessEqual(chunk['end_char'], section['end_char'])
                self.assertEqual(chunk['section_name'], section['name'])
            else:
                self.assertEqual(chunk['section_scope'], 'unsectioned')
        assert_coverage(self, source, chunks)

    def test_overlap_and_progress(self):
        for strategy in STRATEGIES:
            for overlap in (0, 20, 99):
                config = replace(CONFIG, strategy=strategy, overlap=overlap)
                source = document(parts=[('1', 'Business', 'A long sentence. ' * 25)], preamble='')
                chunks = chunk_document(source, config)
                for previous, current in zip(chunks, chunks[1:]):
                    self.assertGreater(current['start_char'], previous['start_char'])
                    self.assertEqual(previous['end_char'] - current['start_char'], overlap)
                    self.assertEqual(current['overlap_with_previous'], overlap)
                    if overlap:
                        self.assertEqual(previous['text'][-overlap:], current['text'][:overlap])
                self.assertTrue(all(len(c['text']) <= config.chunk_size for c in chunks))
                assert_coverage(self, source, chunks)

    def test_natural_boundaries(self):
        source = plain_document('A' * 58 + '\n\n' + 'B' * 60 + '\n\n' + 'C' * 60)
        recursive = chunk_document(source, replace(CONFIG, strategy='recursive', overlap=0))
        self.assertEqual(recursive[0]['end_char'], 60)
        sentence = plain_document('A' * 57 + '. ' + 'B' * 100)
        chunks = chunk_document(sentence, replace(CONFIG, strategy='recursive', overlap=0))
        self.assertEqual(chunks[0]['end_char'], 59)
        self.assertEqual(chunk_document(source, CONFIG)[0]['end_char'], 100)

    def test_orphan_rebalancing(self):
        source = plain_document('x' * 105)
        for strategy in STRATEGIES:
            chunks = chunk_document(source, replace(CONFIG, strategy=strategy, overlap=0))
            self.assertEqual([len(c['text']) for c in chunks], [75, 30])
            assert_coverage(self, source, chunks)

        source = plain_document('x' * 205)
        chunks = chunk_document(source, replace(CONFIG, overlap=0, min_chunk_size=90))
        self.assertEqual([len(c['text']) for c in chunks], [100, 53, 52])
        assert_coverage(self, source, chunks)

    def test_tables_and_fallback_long_unbroken_text(self):
        value = 'Revenue | 2025 | 2024\n' + 'Sales | 12345 | (234)\n' * 50
        source = plain_document(value)
        source['content'][0]['type'] = 'table'
        for strategy in STRATEGIES:
            chunks = chunk_document(source, replace(CONFIG, strategy=strategy))
            assert_coverage(self, source, chunks)
            self.assertTrue(all(c['table_fragments'] for c in chunks))
            for chunk in chunks:
                table = chunk['table_fragments'][0]
                self.assertEqual(table['block_index'], 0)
                self.assertTrue(table['is_partial'])
                self.assertEqual(table['start_char'], chunk['start_char'])
                self.assertEqual(table['end_char'], chunk['end_char'])
            unbroken = plain_document('x' * 300)
            fallback = chunk_document(unbroken, replace(CONFIG, strategy=strategy))
            assert_coverage(self, unbroken, fallback)
            self.assertLessEqual(max(len(c['text']) for c in fallback), CONFIG.chunk_size)

    def test_global_chunks_reference_all_intersected_sections(self):
        source = document(parts=[('1', 'Business', 'A'), ('6', 'Reserved', 'B')], preamble='')
        for strategy in ('fixed_size', 'recursive'):
            chunks = chunk_document(source, replace(CONFIG, strategy=strategy))
            self.assertEqual(len(chunks), 1)
            self.assertEqual([s['item'] for s in chunks[0]['sections']], ['1', '6'])
            self.assertIsNone(chunks[0]['item'])
            self.assertEqual(chunks[0]['section_scope'], 'mixed')

    def test_missing_sections_and_unassigned_content(self):
        for strategy in STRATEGIES:
            source = plain_document('No detected sections. ' * 30)
            chunks = chunk_document(source, replace(CONFIG, strategy=strategy))
            assert_coverage(self, source, chunks)
            self.assertTrue(all(c['item'] is None for c in chunks))
            self.assertEqual(chunk_document(plain_document(''), replace(CONFIG, strategy=strategy)), [])

    def test_invalid_config_and_offsets(self):
        for kwargs in ({'chunk_size': 0}, {'overlap': -1}, {'overlap': 100},
                       {'min_chunk_size': 101}, {'chunk_size': True},
                       {'boundary_min_fraction': 0}, {'strategy': 'unknown'}):
            with self.assertRaises(ValueError):
                replace(CONFIG, **kwargs)
        source = document()
        source['sections'][0]['end_char'] += 1
        with self.assertRaises(ValueError):
            chunk_document(source, CONFIG)
        source = document()
        del source['source_url']
        with self.assertRaises(ValueError):
            chunk_document(source, CONFIG)

    def test_no_cross_document_chunks_and_repeat_run(self):
        sources = [plain_document('A' * 500), plain_document('B' * 400)]
        sources[1]['document_id'] = 'EX_002'
        with tempfile.TemporaryDirectory() as directory:
            for strategy in STRATEGIES:
                config = replace(CONFIG, strategy=strategy)
                destination, summary = generate_experiment(sources, config, directory)
                self.assertEqual(summary['filing_count'], 2)
                paths = list(destination.glob('*.json'))
                before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
                destination_again, summary_again = generate_experiment(list(reversed(sources)), config, directory)
                self.assertEqual(destination, destination_again)
                self.assertEqual(summary, summary_again)
                self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths})
                for source in sources:
                    chunks = json.loads((destination / f"{source['document_id']}.json").read_text())['chunks']
                    assert_coverage(self, source, chunks)
                    self.assertTrue(all(c['source_document_id'] == source['document_id'] for c in chunks))
                    self.assertTrue(all(set(c['text']) == set(source['text']) for c in chunks))
                changed, _ = generate_experiment(sources, replace(config, chunk_size=120), directory)
                self.assertNotEqual(destination, changed)
            self.assertEqual({p.name for p in Path(directory).iterdir()}, set(STRATEGIES))
            changed_sources = [plain_document('C' * 500)]
            changed, _ = generate_experiment(changed_sources, config, directory)
            self.assertNotEqual(destination, changed)
            with self.assertRaises(ValueError):
                generate_experiment([sources[0], sources[0]], config, directory)

    def test_statistics(self):
        chunks = chunk_document(plain_document('x' * 205), replace(CONFIG, overlap=0))
        stats = summarize(chunks, CONFIG)
        self.assertEqual(stats['total_chunks'], 3)
        self.assertEqual(stats['minimum_characters'], 30)
        self.assertEqual(stats['maximum_characters'], 100)
        self.assertEqual(stats['median_characters'], 75)
        self.assertEqual(stats['very_small_chunks'], 0)

    def test_cli_and_errors(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            root = Path(directory)
            (root / 'parsed').mkdir()
            (root / 'parsed/example.json').write_text(json.dumps(document()))
            settings = {'input_dir': 'parsed', 'output_dir': 'chunks',
                        'defaults': {'chunk_size': 100, 'overlap': 20, 'min_chunk_size': 30,
                                     'boundary_min_fraction': 0.5},
                        'experiments': [{'strategy': s} for s in STRATEGIES]}
            (root / 'config.json').write_text(json.dumps(settings))
            self.assertEqual(main(['--root', directory, '--config', 'config.json']), 0)
            self.assertEqual(len(list((root / 'chunks').rglob('summary.json'))), 3)
            self.assertEqual(main(['--root', directory, '--config', 'missing.json']), 1)
            (root / 'parsed/example.json').write_text('{invalid')
            self.assertEqual(main(['--root', directory, '--config', 'config.json']), 1)


class ChunkingCorpusTests(unittest.TestCase):
    def test_all_documents_all_strategies(self):
        paths = sorted((ROOT / 'data/processed/parsed').glob('*.json'))
        if not paths:
            self.skipTest('Parsed corpus unavailable')
        self.assertEqual(len(paths), 9)
        settings = json.loads((ROOT / 'configs/chunking.json').read_text())
        seen_ids = set()
        for experiment in settings['experiments']:
            config = ChunkingConfig(**{**settings['defaults'], **experiment})
            for path in paths:
                with self.subTest(strategy=config.strategy, document=path.stem):
                    source = json.loads(path.read_text())
                    chunks = chunk_document(source, config)
                    assert_coverage(self, source, chunks)
                    self.assertTrue(all(0 < len(c['text']) <= config.chunk_size for c in chunks))
                    for chunk in chunks:
                        self.assertNotIn(chunk['chunk_id'], seen_ids)
                        seen_ids.add(chunk['chunk_id'])
                    if config.strategy == 'sec_section':
                        self.assertTrue(all(len(c['sections']) <= 1 for c in chunks))
                        self.assertEqual({c['item'] for c in chunks if c['item']},
                                         {s['item'] for s in source['sections']})
                    for index, block in enumerate(source['content']):
                        if block['type'] == 'table':
                            fragments = [t for c in chunks for t in c['table_fragments'] if t['block_index'] == index]
                            cursor = block['start_char']
                            for fragment in fragments:
                                self.assertLessEqual(fragment['start_char'], cursor)
                                cursor = max(cursor, fragment['end_char'])
                            self.assertEqual(cursor, block['end_char'])


if __name__ == '__main__':
    unittest.main()
