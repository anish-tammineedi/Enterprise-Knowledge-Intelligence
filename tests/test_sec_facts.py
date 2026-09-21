import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.agentic.financial_tool import LocalFinancialData, financial_tool
from src.agentic.sec_facts import CompanyFactsClient, cache_company_facts, normalize_company_facts, select_fact_rows
from src.agentic.tools import execute_tool


COMPANY = {'ticker': 'AAPL', 'company': 'Apple Inc.', 'cik': '0000320193'}


def payload():
    rows = [
        {'fy': 2024, 'fp': 'FY', 'form': '10-K', 'filed': '2024-11-01', 'accn': 'old', 'val': 90, 'start': '2023-10-01', 'end': '2024-09-28'},
        {'fy': 2024, 'fp': 'FY', 'form': '10-K/A', 'filed': '2025-01-01', 'accn': 'new', 'val': 100, 'start': '2023-10-01', 'end': '2024-09-28'}]
    anchors = [{k: v for k, v in r.items() if k != 'start'} for r in rows]
    return {'cik': 320193, 'facts': {'us-gaap': {
        'SalesRevenueNet': {'units': {'USD': rows}},
        'Assets': {'units': {'USD': anchors}}}}}


class SecFactsTests(unittest.TestCase):
    def test_raw_payload_retained_even_when_normalization_fails(self):
        original = payload()
        class Client:
            def get(self, url):
                return original
        with tempfile.TemporaryDirectory() as directory:
            with patch('src.agentic.sec_facts.normalize_company_facts', side_effect=ValueError('test failure')):
                with self.assertRaises(ValueError):
                    cache_company_facts(Client(), COMPANY, directory)
            raw_files = list((Path(directory) / 'raw').glob('*.json'))
            self.assertEqual(len(raw_files), 1)
            self.assertEqual(json.loads(raw_files[0].read_text()), original)
            self.assertFalse((Path(directory) / 'AAPL.json').exists())
            cache_company_facts(Client(), COMPANY, directory)
            self.assertEqual(len(list((Path(directory) / 'raw').glob('*.json'))), 1)
            self.assertEqual(LocalFinancialData.from_cache_dir(directory).lookup('AAPL', 2024, 'revenue')['value'], 100)

    def test_normalized_cache_is_not_a_raw_payload(self):
        with self.assertRaisesRegex(ValueError, 'Raw SEC Company Facts'):
            normalize_company_facts({'company': COMPANY, 'metrics': {'revenue': {}}}, COMPANY)

    def test_normalization_lookup_and_provenance(self):
        facts = normalize_company_facts(payload(), COMPANY)
        self.assertEqual(facts['revenue'][2024]['value'], 100)
        self.assertEqual(facts['revenue'][2024]['concept'], 'SalesRevenueNet')
        result = execute_tool(financial_tool(LocalFinancialData(facts={'AAPL': {'2024': {'revenue': [facts['revenue'][2024]]}}})), {'ticker': 'AAPL', 'fiscal_year': 2024, 'metric': 'revenue'})
        self.assertEqual(result.status, 'success')
        self.assertEqual(result.evidence[0]['cik'], '0000320193')
        self.assertEqual(result.evidence[0]['unit'], 'USD')

    def test_unavailable_duplicate_ambiguous_and_wrong_concept(self):
        p = payload()
        rows = p['facts']['us-gaap']['SalesRevenueNet']['units']['USD']
        rows.append(dict(rows[-1]))
        self.assertEqual(normalize_company_facts(p, COMPANY)['revenue'][2024]['value'], 100)
        rows.append(rows[-1] | {'val': 101})
        self.assertNotIn(2024, normalize_company_facts(p, COMPANY)['revenue'])
        data = LocalFinancialData(facts={'AAPL': {'2024': {'revenue': [{'concept': 'Wrong', 'value': 1}]}}})
        self.assertIsNone(data.lookup('AAPL', 2024, 'revenue'))
        self.assertEqual(execute_tool(financial_tool(data), {'ticker': 'AAPL', 'fiscal_year': 2030, 'metric': 'revenue'}).status, 'unavailable')

    def test_comparatives_and_quarters_are_not_annual_conflicts(self):
        p = payload()
        rows = p['facts']['us-gaap']['SalesRevenueNet']['units']['USD']
        rows.extend([rows[-1] | {'end': '2023-09-30', 'start': '2022-10-01', 'val': 80},
                     rows[-1] | {'start': '2024-07-01', 'val': 25}])
        result = normalize_company_facts(p, COMPANY)['revenue'][2024]
        self.assertEqual(result['value'], 100)
        self.assertEqual(result['accession_number'], 'new')
        self.assertEqual(result['form'], '10-K/A')

    def test_no_anchor_invalid_shape_and_wrong_cik_fail_closed(self):
        p = payload()
        p['facts']['us-gaap'].pop('Assets')
        self.assertEqual(normalize_company_facts(p, COMPANY)['revenue'], {})
        p['cik'] = 1
        with self.assertRaises(ValueError):
            normalize_company_facts(p, COMPANY)
        p = payload()
        p['facts']['us-gaap']['Assets']['units']['USD'] = {}
        with self.assertRaises(ValueError):
            normalize_company_facts(p, COMPANY)

    def test_units_invalid_year_and_conflicting_durations_rejected(self):
        p = payload()
        units = p['facts']['us-gaap']['SalesRevenueNet']['units']
        units['EUR'] = units.pop('USD')
        self.assertEqual(normalize_company_facts(p, COMPANY)['revenue'], {})
        p = payload()
        rows = p['facts']['us-gaap']['SalesRevenueNet']['units']['USD']
        rows.append(rows[-1] | {'start': '2023-09-30'})
        self.assertEqual(normalize_company_facts(p, COMPANY)['revenue'], {})
        for row in rows:
            row['fy'] = True
        self.assertEqual(normalize_company_facts(p, COMPANY)['revenue'], {})

    def test_deterministic_cache_client_headers_and_missing_user_agent(self):
        with self.assertRaises(ValueError):
            CompanyFactsClient({'user_agent_env': 'MISSING', 'timeout_seconds': 1, 'request_interval_seconds': 0})
        a = normalize_company_facts(payload(), COMPANY)
        self.assertEqual(a, normalize_company_facts(copy.deepcopy(payload()), COMPANY))


if __name__ == '__main__':
    unittest.main()
