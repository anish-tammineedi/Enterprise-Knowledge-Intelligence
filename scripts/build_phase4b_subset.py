import argparse
import json
from pathlib import Path

from src.evaluation.generation_metrics import select_subset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--benchmark', default='evals/ground_truth/sec_retrieval_benchmark.json')
    parser.add_argument('--output', default='evals/generation/phase4b/subset.json')
    args = parser.parse_args()
    benchmark = json.loads(Path(args.benchmark).read_text())
    questions = select_subset(benchmark['questions'])
    result = {'phase': '4B', 'method': 'For each category in lexicographic order, select the lowest question ID for each available difficulty in easy, medium, hard order, then the lowest remaining ID until two questions are selected.', 'generation_calls_required': len(questions), 'question_ids': [q['question_id'] for q in questions], 'questions': questions}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'count': len(questions), 'question_ids': result['question_ids']}, indent=2))


if __name__ == '__main__':
    main()
