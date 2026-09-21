"""Offline normalization and diagnostics from retained SEC Company Facts JSON."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agentic.financial_tool import METRIC_CONCEPTS, LocalFinancialData, financial_tool
from src.agentic.sec_facts import COMPANY_FACTS_URL, normalize_cik, select_fact_rows, validate_raw_payload
from src.agentic.tools import execute_tool
from src.generation.retrieval import verify_protected


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify reproducibility without writing files')
    args = parser.parse_args()
    config = json.loads((ROOT / 'configs/sec_company_facts.json').read_text())
    cache = ROOT / config['cache_dir']
    report = {'companies': {}, 'normalization_version': 2}
    for company in config['companies']:
        ticker = company['ticker']
        paths = sorted((cache / 'raw').glob(ticker + '-*.json'))
        if len(paths) != 1:
            raise ValueError('Exactly one retained raw version required for ' + ticker)
        raw_path = paths[0]
        raw_sha = sha(raw_path)
        if raw_path.stem != ticker + '-' + raw_sha:
            raise ValueError('Raw content hash mismatch')
        payload = json.loads(raw_path.read_text())
        validate_raw_payload(payload, company)
        metrics, diagnostics = {}, {}
        for metric in METRIC_CONCEPTS:
            diag = {}
            metrics[metric] = select_fact_rows(payload, company, metric, diag)
            for row in metrics[metric].values():
                row.update(raw_file=str(raw_path.relative_to(ROOT)), raw_sha256=raw_sha)
                raw_row = payload['facts']['us-gaap'][row['concept']]['units'][row['unit']][int(row['raw_fact_pointer'].split('/')[-1])]
                assert raw_row['val'] == row['value'] and raw_row['accn'] == row['accession_number']
            diagnostics[metric] = diag
        normalized = {'company': company, 'source_url': COMPANY_FACTS_URL.format(cik=normalize_cik(company['cik'])),
                      'normalization_version': 2, 'raw_file': str(raw_path.relative_to(ROOT)),
                      'raw_sha256': raw_sha, 'metrics': metrics}
        encoded = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        path = cache / (ticker + '.json')
        if args.check:
            if path.read_text() != encoded:
                raise ValueError('Non-reproducible normalized cache: ' + ticker)
        else:
            temporary = path.with_suffix('.json.tmp')
            temporary.write_text(encoded, encoding='utf-8')
            temporary.replace(path)
        report['companies'][ticker] = {'raw_file': str(raw_path.relative_to(ROOT)), 'raw_sha256': raw_sha,
            'normalized_sha256': sha(path), 'metrics': diagnostics}
        print(ticker, {metric: len(rows) for metric, rows in metrics.items()})
        if ticker == 'AAPL':
            concept = METRIC_CONCEPTS['revenue'][0]
            report['apple_2025_trace'] = {
                'concept': concept,
                'annual_fy2025_raw_rows': [r for r in payload['facts']['us-gaap'][concept]['units']['USD'] if r.get('fy') == 2025 and r.get('fp') == 'FY' and r.get('form') in ('10-K', '10-K/A')],
                'normalized_fact': metrics['revenue'].get(2025)}
    tool = financial_tool(LocalFinancialData.from_cache_dir(cache))
    inputs = [{'ticker': 'AAPL', 'fiscal_year': 2025, 'metric': 'revenue'},
              {'ticker': 'MSFT', 'fiscal_year': 2025, 'metric': 'net_income'},
              {'ticker': 'NVDA', 'fiscal_year': 2025, 'metric': 'revenue'},
              {'ticker': 'AAPL', 'fiscal_year': 1900, 'metric': 'revenue'}]
    report['direct_tool_tests'] = []
    for i, payload in enumerate(inputs):
        result = execute_tool(tool, payload)
        assert result.status == ('unavailable' if i == 3 else 'success')
        report['direct_tool_tests'].append({'input': payload, 'result': asdict(result)})
    manifest = json.loads((ROOT / 'configs/generation_protected.json').read_text())
    verify_protected(ROOT, manifest)
    old = json.loads((ROOT / 'evals/generation/phase5/protected_audit.json').read_text())['sha256']
    assert all(sha(ROOT / p) == h for p, h in old.items())
    benchmark_sha = sha(ROOT / 'evals/ground_truth/sec_retrieval_benchmark.json')
    assert benchmark_sha == '74a2e70d531e389a47730e8c537329ec65cfae5134abec3739a9297feba47e86'
    report['validation'] = {'protected_files_unchanged': len(old), 'benchmark_sha256': benchmark_sha,
                            'raw_hashes_verified': True, 'all_accepted_facts_match_raw_value_and_accession': True}
    if not args.check:
        (ROOT / 'evals/generation/phase5/financial_rebuild_report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('Protected artifacts verified; caches reproducible.' if args.check else 'Rebuilt offline; protected artifacts verified.')


if __name__ == '__main__':
    main()
