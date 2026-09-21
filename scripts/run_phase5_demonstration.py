"""Run the four prepared Phase 5 questions using cached evidence and local Ollama."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agentic.document_tool import document_tool
from src.agentic.financial_tool import LocalFinancialData, financial_tool
from src.agentic.orchestrator import Orchestrator
from src.agentic.response import evidence_contexts
from src.embeddings.local_dense import write_json
from src.generation.contracts import Question
from src.generation.pipeline import generate, prepare
from src.generation.providers import create_provider
from src.generation.retrieval import SECSectionRetriever, verify_protected


class EvidenceRetriever:
    def __init__(self, trace):
        self.chunks = evidence_contexts(trace)

    def retrieve(self, query, mode, top_k):
        return self.chunks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    config = json.loads((ROOT / 'configs/generation_ollama.json').read_text())
    output = ROOT / 'evals/generation/phase5'
    config['output_dir'] = str(output.relative_to(ROOT))
    manifest = json.loads((ROOT / config['protected_manifest']).read_text())
    verify_protected(ROOT, manifest)
    protected = [p for base in ('data/raw', 'data/metadata', 'data/processed/parsed', 'data/processed/chunks', 'evals/ground_truth', 'evals/results', 'evals/generation/phase4a', 'evals/generation/phase4a_ollama', 'evals/generation/phase4b') for p in (ROOT / base).rglob('*') if p.is_file()]
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    orchestrator = Orchestrator(document_tool(SECSectionRetriever(ROOT, config['retrieval']), config['retrieval']), financial_tool(LocalFinancialData.from_cache_dir(ROOT / 'data/processed/sec_company_facts')))
    provider = create_provider('ollama') if args.live else None
    rows = []
    try:
        for row in json.loads((ROOT / 'evals/phase5_demonstration.json').read_text())['questions']:
            trace = orchestrator.execute(row['question'])
            question = Question(row['question_id'], row['question'])
            retriever = EvidenceRetriever(trace)
            if args.live:
                result, path = generate(question, retriever, provider, config, output / 'traces')
            else:
                result, _, _ = prepare(question, retriever, config)
                result['status'] = 'prepared_only_no_model_call'
                path = output / 'prepared' / (question.question_id + '.json')
                write_json(path, result)
            record = {'question_id': question.question_id, 'orchestration': trace, 'routing_matches': trace['selected_tools'] == row['expected_routing'], 'generation_status': result['status'], 'parsed_answer': result.get('parsed_answer'), 'generation_trace': str(path.relative_to(ROOT))}
            rows.append(record)
            write_json(output / ('live_report.json' if args.live else 'prepared_report.json'), {'live': args.live, 'questions': rows, 'limitation': 'Downloaded normalized caches contain no accepted facts. Raw SEC responses were not retained by the downloader; financial lookups remain unavailable.'})
            print(question.question_id, result['status'], flush=True)
    finally:
        verify_protected(ROOT, manifest)
        after = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in before}
        write_json(output / 'protected_audit.json', {'unchanged': before == after, 'sha256': after})
        if before != after:
            raise ValueError('Protected artifacts changed')
    return int(any(r['generation_status'] not in ('success', 'prepared_only_no_model_call') or not r['routing_matches'] for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
