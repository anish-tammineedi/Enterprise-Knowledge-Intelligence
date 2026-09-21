import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingestion.chunking import ChunkingConfig, STRATEGIES, generate_experiment


def main(argv=None):
    parser = argparse.ArgumentParser(description='Generate configurable SEC chunking experiments')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--config', type=Path, default=Path('configs/chunking.json'))
    parser.add_argument('--strategy', choices=STRATEGIES, action='append')
    args = parser.parse_args(argv)
    try:
        settings = json.loads((args.root / args.config).read_text(encoding='utf-8'))
        experiments = [ChunkingConfig(**{**settings['defaults'], **experiment})
                       for experiment in settings['experiments']
                       if not args.strategy or experiment['strategy'] in args.strategy]
        if not experiments:
            raise ValueError('No experiments selected')
        documents = [json.loads(path.read_text(encoding='utf-8'))
                     for path in sorted((args.root / settings['input_dir']).glob('*.json'))]
        for config in experiments:
            destination, summary = generate_experiment(documents, config, args.root / settings['output_dir'])
            print(f"{config.strategy}: {summary['filing_count']} filings, {summary['total_chunks']} chunks, "
                  f"mean {summary['average_characters']}, median {summary['median_characters']}, "
                  f"range {summary['minimum_characters']}–{summary['maximum_characters']}, "
                  f"very small {summary['very_small_chunks']}")
            for document_id, stats in summary['per_filing'].items():
                print(f"  {document_id}: {stats['total_chunks']} chunks")
            print(f"  Section distribution: {json.dumps(summary['section_distribution'], sort_keys=True)}")
            print(f'  Output: {destination}')
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'Chunking failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
