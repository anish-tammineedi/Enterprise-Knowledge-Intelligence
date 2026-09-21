import unittest

from src.agentic.orchestrator import Orchestrator
from src.agentic.response import evidence_contexts
from src.agentic.financial_tool import LocalFinancialData, financial_tool
from src.agentic.document_tool import document_tool
from src.generation.grounding import PROVENANCE_FIELDS
from tests.test_agentic import specs


class Phase5IntegrationTests(unittest.TestCase):
    def test_company_name_resolves_and_unit_reaches_prompt(self):
        d, _ = specs()
        row = {'concept': 'SalesRevenueNet', 'value': 100, 'unit': 'USD', 'end': '2025-09-27'}
        f = financial_tool(LocalFinancialData(facts={'AAPL': {'2025': {'revenue': [row]}}}))
        trace = Orchestrator(d, f).execute('What was Apple’s revenue in fiscal 2025?')
        self.assertEqual(trace['tool_results'][0]['status'], 'success')
        context = evidence_contexts(trace)[0]
        self.assertIn('100 USD', context['text'])
        self.assertEqual(context['report_date'], '2025-09-27')

    def test_document_provenance_is_preserved(self):
        chunk = dict.fromkeys(PROVENANCE_FIELDS, '')
        chunk.update(chunk_id='c', text='Evidence', start_char=0, end_char=8, filing_date='2025-10-31', report_date='2025-09-27')
        class Retriever:
            def retrieve(self, *args):
                return [chunk]
        d = document_tool(Retriever(), {})
        _, f = specs()
        trace = Orchestrator(d, f).execute('Describe Apple business')
        self.assertEqual(trace['tool_results'][0]['evidence'][0], chunk)
        self.assertEqual(evidence_contexts(trace)[0]['text'], 'Evidence')
