import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.download_sec_filings import SecClient, process_company


class Session:
    def __init__(self):
        self.headers = {}


class SecDownloadConfigurationTests(unittest.TestCase):
    def test_user_agent_is_required_and_never_falls_back_to_a_generic_value(self):
        session = Session()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'SEC_USER_AGENT'):
                SecClient(session=session)
        self.assertEqual(session.headers, {})

    def test_configured_user_agent_is_applied_without_a_request(self):
        session = Session()
        value = 'PortfolioProject/1.0 (contact: operator-placeholder)'
        with patch.dict(os.environ, {'SEC_USER_AGENT': value}, clear=True):
            SecClient(session=session)
        self.assertEqual(session.headers['User-Agent'], value)
        self.assertEqual(session.headers['Accept-Encoding'], 'gzip, deflate')

    def test_redownload_preserves_existing_provenance_timestamp_and_order(self):
        accession = '0000320193-25-000079'
        prior = {'company': 'Apple Inc.', 'ticker': 'AAPL', 'cik': '0000320193', 'form': '10-K',
                 'filing_date': '2025-10-31', 'report_date': '2025-09-27',
                 'accession_number': accession,
                 'source_url': 'https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl.htm',
                 'downloaded_at': '2026-09-15T00:11:25.712879+00:00',
                 'local_path': 'data/raw/sec_filings/AAPL_000032019325000079.html'}
        sources = {'source': 'U.S. Securities and Exchange Commission EDGAR', 'documents': [prior]}

        class Response:
            content = b'<html>filing</html>'

            def __init__(self, body=None): self.body = body
            def json(self): return self.body
            def raise_for_status(self): pass

        class Client:
            def get(self, url):
                if 'submissions/' in url:
                    return Response({'filings': {'recent': {
                        'form': ['10-K'], 'accessionNumber': [accession], 'filingDate': ['2025-10-31'],
                        'reportDate': ['2025-09-27'], 'primaryDocument': ['aapl.htm']}}})
                return Response()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata_path = root / 'sources.json'
            metadata_path.write_text(json.dumps(sources, indent=2) + '\n')
            local_filing = root / 'data/raw/sec_filings/AAPL_000032019325000079.html'
            with patch('scripts.download_sec_filings.ROOT', root), \
                 patch('scripts.download_sec_filings.SOURCES_PATH', metadata_path), \
                 patch('scripts.download_sec_filings.filing_path', return_value=local_filing):
                counts = process_company(Client(), {'name': 'Apple Inc.', 'ticker': 'AAPL', 'cik': '0000320193'},
                                         1, sources)
            self.assertEqual(counts, (1, 0, 0))
            self.assertEqual(local_filing.read_bytes(), b'<html>filing</html>')
            self.assertEqual(metadata_path.read_text(), json.dumps(sources, indent=2) + '\n')
            self.assertEqual(sources['documents'], [prior])


if __name__ == '__main__':
    unittest.main()
