import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embeddings.local_dense import digest, write_json
from src.generation.contracts import Question
from src.generation.pipeline import generate, prepare
from src.generation.providers import create_provider
from src.generation.retrieval import SECSectionRetriever, verify_protected


SAMPLE_CATEGORIES = ('direct_factual', 'numerical', 'multi_hop', 'unanswerable')


def sample_questions(benchmark):
    return [Question(row['question_id'], row['question']) for category in SAMPLE_CATEGORIES
            for row in [next(q for q in benchmark['questions'] if q['category'] == category)]]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prepare or run a four-question grounded generation sample')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--config', type=Path, default=Path('configs/generation.json'))
    parser.add_argument('--mode', choices=['bm25', 'hybrid'])
    parser.add_argument('--top-k', type=int, choices=[5, 10])
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    config = deepcopy(json.loads((root / args.config).read_text()))
    if args.mode:
        config['retrieval']['mode'] = args.mode
    if args.top_k:
        config['retrieval']['top_k'] = args.top_k
    manifest = json.loads((root / config['protected_manifest']).read_text())
    verify_protected(root, manifest)
    output = (root / config['output_dir']).resolve()
    if any(output.is_relative_to((root / directory).resolve()) for directory in manifest['roots']):
        raise ValueError('Generation output must not be inside a protected directory')
    try:
        questions = sample_questions(json.loads((root / 'evals/ground_truth/sec_retrieval_benchmark.json').read_text()))
        retriever = SECSectionRetriever(root, config['retrieval'])
        provider = create_provider(config['llm']['provider']) if args.live else None
        failures = 0
        for question in questions:
            if args.live:
                trace, path = generate(question, retriever, provider, config, output / 'traces')
                failures += trace['status'] != 'success'
                print(question.question_id, trace['status'], path)
            else:
                prepared, _, _ = prepare(question, retriever, config)
                prepared.pop('retrieval_latency_seconds')
                prepared['status'] = 'prepared_only_no_model_call'
                path = output / 'prepared' / (digest(prepared) + '.json')
                write_json(path, prepared)
                print(question.question_id, 'prepared_only', path)
        return int(bool(failures))
    finally:
        verify_protected(root, manifest)


if __name__ == '__main__':
    raise SystemExit(main())
