import json
from pathlib import Path
import tempfile
import unittest

from scripts.parse_sec_filings import main
from src.ingestion.sec_parser import ITEM_ORDER, parse_filing, parse_html, save_document


ROOT = Path(__file__).resolve().parents[1]
METADATA = {
    'company': 'Example', 'ticker': 'EX', 'cik': '0000000001', 'form': '10-K',
    'filing_date': '2025-02-01', 'report_date': '2024-12-31',
    'accession_number': '0000000001-25-000001',
    'source_url': 'https://www.sec.gov/Archives/example.htm', 'local_path': 'example.html',
}


def parse(html):
    return parse_html(html.encode(), METADATA)


class ParserTests(unittest.TestCase):
    def test_hidden_and_inline_content(self):
        result = parse('''<style>bad style</style><script>bad script</script>
            <div hidden>bad hidden</div><div style="DISPLAY: none !important">bad display</div>
            <div style="visibility: hidden">bad visibility</div>
            <ix:header>bad xbrl</ix:header><!--bad comment-->
            <p>Re<span>venue</span> was <ix:nonfraction>1,234</ix:nonfraction>.</p>
            <p>Next&nbsp; paragraph<br>Another line</p>''')
        self.assertNotIn('bad', result['text'])
        self.assertEqual(result['text'], 'Revenue was 1,234.\n\nNext paragraph\n\nAnother line')

    def test_xbrl_block_wrappers_and_missing_items(self):
        result = parse('''<ix:nonnumeric><div>Item 1. Business</div><p>Business body.</p>
            <div>Item 7. Management’s Discussion and Analysis</div><p>Analysis.</p>
            <div>Item 9A. Controls and Procedures</div><p>Controls.</p></ix:nonnumeric>''')
        self.assertEqual([s['item'] for s in result['sections']], ['1', '7', '9A'])
        self.assertIn('Business body.', result['sections'][0]['text'])
        self.assertNotIn('Analysis.', result['sections'][0]['text'])
        for section in result['sections']:
            self.assertEqual(result['text'][section['start_char']:section['end_char']], section['text'])

    def test_toc_links_tables_and_references(self):
        result = parse('''<table><tr><td>Item 1.</td><td>Business</td><td>3</td></tr>
            <tr><td>Item 7.</td><td>Management’s Discussion</td><td>30</td></tr></table>
            <p><a href="#business">Item 1. Business</a></p>
            <p id="business">ITEM 1. BUSI<span>NESS</span></p><p>Actual business.</p>
            <p>See Item 7 for discussion.</p><p>Item 7</p>
            <p>ITEM 7. MANAGEMENT’S DISCUSSION AND ANALYSIS</p><p>Actual analysis.</p>''')
        self.assertEqual(len(result['sections']), 2)
        self.assertTrue(result['sections'][0]['text'].startswith('ITEM 1. BUSINESS'))
        self.assertIn('Actual business.', result['sections'][0]['text'])
        self.assertEqual(result['statistics']['table_count'], 1)

    def test_tables_preserve_cells_and_spans(self):
        result = parse('''<h2>Item 8. Financial Statements and Supplementary Data</h2>
            <table><tr><th rowspan="2">Revenue</th><th colspan="2">2025</th></tr>
            <tr><td><p>$</p><p><ix:nonfraction>1,234</ix:nonfraction></p></td><td>(50)</td></tr></table>''')
        table = next(b for b in result['content'] if b['type'] == 'table')
        self.assertEqual(table['text'], 'Revenue | 2025\n$ 1,234 | (50)')
        self.assertEqual(table['rows'][0][0]['rowspan'], '2')
        self.assertEqual(table['rows'][0][1]['colspan'], '2')

    def test_provenance_and_idempotence(self):
        result = parse('<p>Item 1. Business</p><p>Example.</p>')
        for key, value in METADATA.items():
            self.assertEqual(result[key], value)
        self.assertEqual(len(result['source_sha256']), 64)
        self.assertEqual(result, parse('<p>Item 1. Business</p><p>Example.</p>'))
        with tempfile.TemporaryDirectory() as directory:
            path = save_document(result, directory)
            before = path.read_bytes(), path.stat().st_mtime_ns
            save_document(result, directory)
            self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))

    def test_malformed_html_and_no_sections(self):
        result = parse('<div>Visible<p>More <b>text')
        self.assertIn('More text', result['text'])
        self.assertEqual(result['sections'], [])
        self.assertTrue(result['statistics']['warnings'])

    def test_cli_continues_after_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'example.html').write_text('<p>Item 1. Business</p><p>Body</p>')
            (root / 'sources.json').write_text(json.dumps({'documents': [
                {**METADATA, 'local_path': 'missing.html'}, METADATA]}))
            self.assertEqual(main(['--root', directory, '--metadata', 'sources.json', '--output', 'out']), 1)
            self.assertEqual(len(list((root / 'out').glob('*.json'))), 1)


class CorpusTests(unittest.TestCase):
    def test_all_filings(self):
        documents = json.loads((ROOT / 'data/metadata/sources.json').read_text())['documents']
        if not all((ROOT / d['local_path']).exists() for d in documents):
            self.skipTest('Downloaded corpus unavailable')
        self.assertEqual(len(documents), 9)
        for metadata in documents:
            with self.subTest(filing=metadata['local_path']):
                result = parse_filing(metadata, ROOT)
                self.assertEqual([s['item'] for s in result['sections']], ITEM_ORDER)
                self.assertGreater(len(result['text']), 200000)
                self.assertGreater(result['statistics']['table_count'], 40)
                self.assertTrue(any('Revenue' in b['text'] or 'revenue' in b['text']
                                    for b in result['content'] if b['type'] == 'table'))
                for section in result['sections']:
                    self.assertEqual(result['text'][section['start_char']:section['end_char']], section['text'])
                if metadata['ticker'] == 'NVDA':
                    section = next(s for s in result['sections'] if s['item'] == '8')
                    self.assertIn('information required by this Item is set forth', section['text'])
                    self.assertIn('CONSOLIDATED STATEMENTS OF', result['text'].upper())
                    self.assertEqual(len(result['statistics']['warnings']), 1)
                else:
                    self.assertEqual(result['statistics']['warnings'], [])


if __name__ == '__main__':
    unittest.main()
