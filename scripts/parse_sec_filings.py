import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingestion.sec_parser import parse_filing, save_document


def main(argv=None):
    parser = argparse.ArgumentParser(description='Normalize downloaded SEC HTML filings')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--metadata', type=Path, default=Path('data/metadata/sources.json'))
    parser.add_argument('--output', type=Path, default=Path('data/processed/parsed'))
    args = parser.parse_args(argv)
    try:
        documents = json.loads((args.root / args.metadata).read_text(encoding='utf-8'))['documents']
        if not isinstance(documents, list):
            raise ValueError('Metadata documents must be a list')
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Unable to read metadata: {error}', file=sys.stderr)
        return 1
    successful = 0
    for metadata in documents:
        try:
            document = parse_filing(metadata, args.root)
            save_document(document, args.root / args.output)
            stats = document['statistics']
            print(f"{document['document_id']}: {stats['section_count']} sections, "
                  f"{stats['normalized_characters']:,} characters, {stats['table_count']} tables")
            for warning in stats['warnings']:
                print(f'  WARNING: {warning}')
            successful += 1
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"Failed {metadata.get('local_path', 'unknown filing')}: {error}", file=sys.stderr)
    print(f'Parsed {successful}/{len(documents)} filings successfully')
    return 0 if successful == len(documents) else 1


if __name__ == '__main__':
    raise SystemExit(main())
