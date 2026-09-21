import argparse
import json
from pathlib import Path

from src.evaluation.generation_metrics import aggregate_generation, evaluate_trace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--benchmark', default='evals/ground_truth/sec_retrieval_benchmark.json')
    parser.add_argument('--traces', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    benchmark = json.loads(Path(args.benchmark).read_text())
    questions = {q['question_id']: q for q in benchmark['questions']}
    policy = {'minimum_nonwhitespace_characters': 32, 'minimum_evidence_fraction': 0.5}
    rows = []
    for path in sorted(Path(args.traces).glob('*.json')):
        trace = json.loads(path.read_text())
        question = questions.get(trace.get('question_id'))
        if question:
            row = evaluate_trace(question, trace, policy)
            row.update(category=question['category'], difficulty=question['difficulty'], question=question['question'],
                       raw_model_output=trace.get('raw_model_output'), citations=trace.get('citations', []),
                       retrieved_context_ids=trace.get('retrieved_context_ids', []))
            rows.append(row)
    groups = {}
    for key in ('category', 'difficulty'):
        groups[key] = {value: aggregate_generation([r for r in rows if r[key] == value])
                       for value in sorted({r[key] for r in rows})}
    result = {'metrics': aggregate_generation(rows), 'breakdowns': groups, 'results': rows}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['metrics'], indent=2))


if __name__ == '__main__':
    main()
