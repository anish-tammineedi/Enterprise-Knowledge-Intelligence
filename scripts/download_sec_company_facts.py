import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agentic.sec_facts import CompanyFactsClient, cache_company_facts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/sec_company_facts.json')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    client = CompanyFactsClient(config)
    paths = []
    for company in config['companies']:
        paths.append(cache_company_facts(client, company, ROOT / config['cache_dir']))
        print(paths[-1])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
