import hashlib
import json
import os
import time
from pathlib import Path

import requests

from src.agentic.financial_tool import METRIC_CONCEPTS


COMPANY_FACTS_URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'


def normalize_cik(cik):
    return str(cik).strip().zfill(10)


ANNUAL_FORMS = ('10-K', '10-K/A')
DURATION_METRICS = ('revenue', 'net_income', 'operating_income')


def validate_raw_payload(payload, company):
    if not isinstance(payload, dict) or not isinstance(payload.get('facts'), dict):
        raise ValueError('Raw SEC Company Facts payload with a facts object is required')
    if normalize_cik(payload.get('cik', '')) != normalize_cik(company['cik']):
        raise ValueError('SEC Company Facts CIK does not match configured company')
    taxonomy = payload['facts'].get('us-gaap')
    if not isinstance(taxonomy, dict):
        raise ValueError('SEC Company Facts us-gaap object is required')
    for fact in taxonomy.values():
        if not isinstance(fact, dict) or not isinstance(fact.get('units'), dict):
            raise ValueError('Invalid concept units object')
        for rows in fact['units'].values():
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError('Invalid concept fact array')


def annual_row_error(row):
    from datetime import date
    if row.get('form') not in ANNUAL_FORMS:
        return 'form_filter'
    if type(row.get('fy')) is not int or not 1900 <= row['fy'] <= 2100:
        return 'fiscal_year_filter'
    if row.get('fp') != 'FY':
        return 'fiscal_period_filter'
    if not isinstance(row.get('accn'), str) or not row['accn'].strip():
        return 'missing_accession'
    try:
        if date.fromisoformat(row['end']) > date.fromisoformat(row['filed']):
            return 'period_after_filing'
    except (KeyError, TypeError, ValueError):
        return 'invalid_date'
    return None


def annual_anchors(payload):
    # Assets is an instant balance-sheet concept. Its latest end in each annual
    # accession identifies that filing's current fiscal period, not a calendar year.
    grouped = {}
    for row in payload['facts']['us-gaap'].get('Assets', {}).get('units', {}).get('USD', []):
        if annual_row_error(row) or row.get('start'):
            continue
        key = (row['fy'], row['filed'], row['accn'], row['form'])
        grouped[key] = max(grouped.get(key, ''), row['end'])
    by_year = {}
    for (year, filed, accn, form), end in grouped.items():
        by_year.setdefault(year, []).append({'filed': filed, 'accn': accn, 'form': form, 'end': end})
    return by_year


def select_fact_rows(payload, company, metric, diagnostics=None):
    from collections import Counter
    from datetime import date
    import math
    validate_raw_payload(payload, company)
    facts = payload['facts']['us-gaap']
    anchors = annual_anchors(payload)
    candidates = []
    stages = Counter()
    concept_inventory = {}
    for priority, concept in enumerate(METRIC_CONCEPTS[metric]):
        units = facts.get(concept, {}).get('units', {})
        all_rows = [r for rows in units.values() for r in rows]
        concept_inventory[concept] = {
            'exists': concept in facts, 'raw_fact_count': len(all_rows),
            'units': sorted(units), 'forms': sorted({r.get('form', '') for r in all_rows}),
            'annual_forms': sorted({r.get('form') for r in all_rows if r.get('form') in ANNUAL_FORMS}),
            'fiscal_years': sorted({r['fy'] for r in all_rows if type(r.get('fy')) is int}),
            'annual_candidate_count': sum(annual_row_error(r) is None for r in all_rows)}
        for unit, rows in units.items():
            for index, row in enumerate(rows):
                error = 'unit_filter' if unit != 'USD' else annual_row_error(row)
                if error is None and (type(row.get('val')) not in (int, float) or not math.isfinite(row['val'])):
                    error = 'invalid_value'
                if error is None:
                    matches = [a for a in anchors.get(row['fy'], []) if a['accn'] == row['accn'] and a['filed'] == row['filed'] and a['form'] == row['form']]
                    if not matches:
                        error = 'missing_annual_period_anchor'
                    elif row['end'] != matches[0]['end']:
                        error = 'comparative_period'
                if error is None:
                    if metric in DURATION_METRICS:
                        try:
                            days = (date.fromisoformat(row['end']) - date.fromisoformat(row['start'])).days + 1
                            if not 350 <= days <= 380:
                                error = 'nonannual_duration'
                        except (KeyError, ValueError, TypeError):
                            error = 'invalid_duration'
                    elif row.get('start'):
                        error = 'instant_metric_has_start'
                stages[error or 'period_eligible'] += 1
                if error is None:
                    candidates.append((priority, concept, unit, index, row))
    output = {}
    unavailable = {}
    for year, year_anchors in sorted(anchors.items()):
        newest_date = max(a['filed'] for a in year_anchors)
        latest_anchors = [a for a in year_anchors if a['filed'] == newest_date]
        if len({a['end'] for a in latest_anchors}) != 1:
            unavailable[year] = 'ambiguous_current_period'
            continue
        matching = [c for c in candidates if c[4]['fy'] == year and c[4]['filed'] == newest_date]
        if not matching:
            unavailable[year] = 'no_eligible_fact_in_latest_annual_filing'
            continue
        priority = min(c[0] for c in matching)
        matching = [c for c in matching if c[0] == priority]
        identities = {(c[4].get('start'), c[4]['end'], c[4]['val'], c[2], c[1]) for c in matching}
        if len(identities) != 1:
            unavailable[year] = 'ambiguous_same_period_values_or_durations'
            continue
        _, concept, unit, index, row = sorted(matching, key=lambda c: (c[4]['accn'], c[3]))[0]
        output[year] = {'company': company['company'], 'ticker': company['ticker'],
                        'cik': normalize_cik(company['cik']), 'fiscal_year': year,
                        'metric': metric, 'concept': concept, 'value': row['val'], 'unit': unit,
                        'form': row['form'], 'filing_date': row['filed'],
                        'accession_number': row['accn'], 'start': row.get('start'), 'end': row['end'],
                        'source_url': COMPANY_FACTS_URL.format(cik=normalize_cik(company['cik'])),
                        'raw_fact_pointer': '/facts/us-gaap/' + concept + '/units/' + unit + '/' + str(index),
                        'duplicate_rows_resolved': len(matching) - 1,
                        'period_anchor': 'Assets: latest instant end in the same annual accession'}
    if diagnostics is not None:
        diagnostics.update(concepts=concept_inventory, filter_counts=dict(stages),
                           period_eligible_count=len(candidates), accepted_count=len(output),
                           selected_concepts=sorted({r['concept'] for r in output.values()}),
                           accepted_fiscal_years=sorted(output), unavailable_years=unavailable)
    return output


def normalize_company_facts(payload, company):
    validate_raw_payload(payload, company)
    return {metric: select_fact_rows(payload, company, metric) for metric in METRIC_CONCEPTS}


class CompanyFactsClient:
    def __init__(self, config, session=None, sleep=time.sleep):
        self.config = config
        self.session = session or requests.Session()
        agent = os.environ.get(config['user_agent_env'])
        if not agent:
            raise ValueError('SEC User-Agent must be supplied through ' + config['user_agent_env'])
        self.session.headers.update({'User-Agent': agent, 'Accept-Encoding': 'gzip, deflate'})
        self.sleep = sleep
        self.last_request = None

    def get(self, url):
        if self.last_request is not None:
            wait = self.config['request_interval_seconds'] - (time.monotonic() - self.last_request)
            if wait > 0:
                self.sleep(wait)
        try:
            response = self.session.get(url, timeout=self.config['timeout_seconds'])
        finally:
            self.last_request = time.monotonic()
        response.raise_for_status()
        return response.json()


def cache_company_facts(client, company, cache_dir):
    raw = client.get(COMPANY_FACTS_URL.format(cik=normalize_cik(company['cik'])))
    # Retain the complete decoded response before normalization, including failures.
    # Keep raw files outside the normalized loader's top-level *.json glob.
    raw_text = json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    raw_path = Path(cache_dir) / 'raw' / (company['ticker'] + '-' + hashlib.sha256(raw_text.encode('utf-8')).hexdigest() + '.json')
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_raw = raw_path.with_suffix('.json.tmp')
    temporary_raw.write_text(raw_text, encoding='utf-8')
    temporary_raw.replace(raw_path)
    normalized = normalize_company_facts(raw, company)
    path = Path(cache_dir) / (company['ticker'] + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({'company': company, 'source_url': COMPANY_FACTS_URL.format(cik=normalize_cik(company['cik'])), 'metrics': normalized}, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(text)
    temporary.replace(path)
    return path
