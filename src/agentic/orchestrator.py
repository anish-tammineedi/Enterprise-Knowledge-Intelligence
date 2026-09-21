import re
import time

from src.agentic.tools import ToolResult, execute_tool


FINANCIAL_TERMS = r'\b(revenue|net income|operating income|total assets|total liabilities|cash|cash equivalents)\b'
NARRATIVE_TERMS = r'\b(risk|risks|business|strategy|cybersecurity|properties|legal proceedings|why|how|describe|explain|drove|change|products|services)\b'


class Orchestrator:
    def __init__(self, document_spec, financial_spec):
        self.document_spec = document_spec
        self.financial_spec = financial_spec

    def route(self, query):
        if not isinstance(query, str) or not query.strip():
            return 'abstain', 'empty query'
        financial = bool(re.search(FINANCIAL_TERMS, query, re.I))
        narrative = bool(re.search(NARRATIVE_TERMS, query, re.I))
        has_year = bool(re.search(r'\b20\d{2}\b', query))
        if financial and narrative:
            return 'document_retrieval+financial_data', 'financial fact requested with narrative explanation'
        if financial and has_year:
            return 'financial_data', 'standardized financial metric and fiscal year detected'
        if narrative:
            return 'document_retrieval', 'SEC narrative or section language detected'
        return 'abstain', 'no supported source pattern detected'

    def execute(self, query):
        started = time.perf_counter()
        route, reason = self.route(query)
        results = []
        if route in ('document_retrieval', 'document_retrieval+financial_data'):
            results.append(execute_tool(self.document_spec, {'query': query}))
        if route in ('financial_data', 'document_retrieval+financial_data'):
            results.append(execute_tool(self.financial_spec, self._financial_input(query)))
        if route == 'abstain':
            status = 'unsupported'
        elif any(r.status == 'success' for r in results):
            status = 'success'
        elif any(r.status == 'invalid_input' for r in results):
            status = 'tool_input_error'
        else:
            status = 'insufficient_evidence'
        return {'query': query, 'selected_tools': route.split('+') if route != 'abstain' else [], 'routing_reason': reason,
                'tool_results': [self._serialize(r) for r in results], 'status': status,
                'latency_seconds': time.perf_counter() - started}

    def _financial_input(self, query):
        ticker = next((x for x in ('AAPL', 'MSFT', 'NVDA') if re.search(r'\b' + x + r'\b', query, re.I)), '')
        if not ticker:
            ticker = next((symbol for name, symbol in (('Apple', 'AAPL'), ('Microsoft', 'MSFT'), ('NVIDIA', 'NVDA')) if re.search(r'\b' + name + r'\b', query, re.I)), '')
        year = re.search(r'\b(20\d{2})\b', query)
        metric = next((m for m in ('revenue', 'net_income', 'operating_income', 'total_assets', 'total_liabilities', 'cash_and_cash_equivalents') if re.search(m.replace('_', r'\s+'), query, re.I)), '')
        return {'ticker': ticker, 'fiscal_year': int(year.group(1)) if year else 0, 'metric': metric}

    def _serialize(self, result):
        return {'tool_name': result.tool_name, 'status': result.status, 'output': result.output,
                'evidence': result.evidence, 'error': result.error, 'latency_seconds': result.latency_seconds}
