import json
from pathlib import Path

from src.agentic.tools import ToolInputError, ToolResult, ToolSpec


METRIC_CONCEPTS = {
    'revenue': ('RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet', 'Revenues'),
    'net_income': ('NetIncomeLoss',),
    'operating_income': ('OperatingIncomeLoss',),
    'total_assets': ('Assets',),
    'total_liabilities': ('Liabilities',),
    'cash_and_cash_equivalents': ('CashAndCashEquivalentsAtCarryingValue',),
}


class LocalFinancialData:
    def __init__(self, path=None, facts=None):
        self.path = Path(path) if path else None
        loaded = facts if facts is not None else (json.loads(self.path.read_text()) if self.path and self.path.exists() else {})
        self.facts = self._flatten(loaded)

    def _flatten(self, loaded):
        if 'metrics' not in loaded:
            return loaded
        ticker = loaded.get('company', {}).get('ticker', '')
        result = {ticker: {}}
        for metric, years in loaded.get('metrics', {}).items():
            for year, row in years.items():
                result[ticker].setdefault(str(year), {}).setdefault(metric, []).append(row)
        return result

    def lookup(self, ticker, year, metric):
        rows = self.facts.get(ticker, {}).get(str(year), {}).get(metric, [])
        if len(rows) != 1:
            return None
        row = rows[0]
        if row.get('concept') not in METRIC_CONCEPTS.get(metric, ()):
            return None
        return row

    @classmethod
    def from_cache_dir(cls, directory):
        merged = {}
        for path in sorted(Path(directory).glob('*.json')):
            loaded = json.loads(path.read_text())
            flattened = cls(facts=loaded).facts
            for ticker, years in flattened.items():
                for year, metrics in years.items():
                    for metric, rows in metrics.items():
                        merged.setdefault(ticker, {}).setdefault(year, {}).setdefault(metric, []).extend(rows)
        return cls(facts=merged)


def financial_tool(data):
    def execute(payload):
        if not isinstance(payload, dict) or not isinstance(payload.get('ticker'), str) or not isinstance(payload.get('fiscal_year'), int) or not isinstance(payload.get('metric'), str):
            raise ToolInputError('ticker, fiscal_year and metric are required')
        ticker, year, metric = payload['ticker'].upper(), payload['fiscal_year'], payload['metric']
        if metric not in METRIC_CONCEPTS:
            raise ToolInputError('unsupported metric')
        row = data.lookup(ticker, year, metric)
        if row is None:
            return ToolResult('financial_data', 'unavailable', {'available': False, 'reason': 'No unambiguous local SEC fact'}, [])
        evidence = [{**row, 'ticker': ticker, 'fiscal_year': year, 'metric': metric, 'concept_mapping': list(METRIC_CONCEPTS[metric]), 'unit': row.get('unit', row.get('units'))}]
        return ToolResult('financial_data', 'success', {'available': True, **evidence[0]}, evidence)
    return ToolSpec('financial_data', 'Look up explicitly mapped SEC/XBRL financial facts in local data.',
                    {'type': 'object', 'required': ['ticker', 'fiscal_year', 'metric']},
                    {'type': 'object', 'required': ['available']}, execute)
