import unittest

from src.agentic.document_tool import document_tool
from src.agentic.financial_tool import LocalFinancialData, financial_tool
from src.agentic.orchestrator import Orchestrator
from src.agentic.tools import execute_tool


class FakeRetriever:
    def retrieve(self, query, mode, top_k):
        return [{'chunk_id': 'c1', 'company': 'Apple', 'ticker': 'AAPL', 'filing_date': '2025-10-31', 'report_date': '2025-09-27', 'accession_number': 'a', 'item': '1', 'section_name': 'Business', 'source_url': 'https://sec', 'text': 'Apple sells products.', 'start_char': 0, 'end_char': 21}]


def specs():
    d = document_tool(FakeRetriever(), {'mode': 'bm25', 'top_k': 5})
    f = financial_tool(LocalFinancialData(facts={'AAPL': {'2025': {'revenue': [{'concept': 'SalesRevenueNet', 'value': 100, 'units': 'USD', 'document_id': 'd', 'source_url': 'https://sec'}]}}}))
    return d, f


class AgenticTests(unittest.TestCase):
    def test_document_routing_and_provenance(self):
        d, f = specs()
        o = Orchestrator(d, f)
        t = o.execute('Explain Apple business strategy')
        self.assertEqual(t['selected_tools'], ['document_retrieval'])
        self.assertEqual(t['tool_results'][0]['evidence'][0]['chunk_id'], 'c1')

    def test_financial_lookup_and_unavailable(self):
        d, f = specs()
        self.assertEqual(execute_tool(f, {'ticker': 'AAPL', 'fiscal_year': 2025, 'metric': 'revenue'}).status, 'success')
        self.assertEqual(execute_tool(f, {'ticker': 'AAPL', 'fiscal_year': 2024, 'metric': 'revenue'}).status, 'unavailable')
        self.assertEqual(execute_tool(f, {'ticker': 'AAPL', 'fiscal_year': 2025, 'metric': 'made_up'}).status, 'invalid_input')

    def test_combined_and_unsupported_routing(self):
        d, f = specs()
        o = Orchestrator(d, f)
        self.assertEqual(o.route('What was AAPL revenue in 2025 and why did it change?')[0], 'document_retrieval+financial_data')
        self.assertEqual(o.execute('Tell me a stock price').get('status'), 'unsupported')

    def test_malformed_and_execution_failure(self):
        d, f = specs()
        self.assertEqual(execute_tool(d, {}).status, 'invalid_input')
        class Broken:
            def retrieve(self, *args):
                raise RuntimeError('secret')
        result = execute_tool(document_tool(Broken(), {}), {'query': 'business'})
        self.assertEqual(result.status, 'error')
        self.assertNotIn('secret', str(result.error))

    def test_deterministic_routing(self):
        d, f = specs()
        o = Orchestrator(d, f)
        self.assertEqual(o.route('What is total assets for MSFT 2025?'), o.route('What is total assets for MSFT 2025?'))


if __name__ == '__main__':
    unittest.main()
