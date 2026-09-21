"""Validate only the two Phase 5 demonstrations affected by the financial rebuild."""
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agentic.document_tool import document_tool
from src.agentic.financial_tool import LocalFinancialData, financial_tool
from src.agentic.orchestrator import Orchestrator
from src.agentic.response import evidence_contexts
from src.embeddings.local_dense import digest, write_json
from src.generation.contracts import LLMConfig, Question, ProviderError
from src.generation.grounding import SCHEMA, build_prompt, validate_output, validate_citation_grounding
from src.generation.providers import create_provider
from src.generation.retrieval import SECSectionRetriever, verify_protected

IDS = ('P5-FIN-001', 'P5-BOTH-001')
OUTPUT = ROOT / 'evals/generation/phase5/financial_revalidation'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    config = json.loads((ROOT / 'configs/generation_ollama.json').read_text())
    llm = LLMConfig(**config['llm'])
    assert llm.provider == 'ollama' and llm.max_retries == 0
    manifest = json.loads((ROOT / config['protected_manifest']).read_text())
    verify_protected(ROOT, manifest)
    old = json.loads((ROOT / 'evals/generation/phase5/live_report.json').read_text())
    protected = dict(json.loads((ROOT / 'evals/generation/phase5/protected_audit.json').read_text())['sha256'])
    for row in old['questions']:
        protected[row['generation_trace']] = sha(ROOT / row['generation_trace'])
    protected['evals/generation/phase5/live_report.json'] = sha(ROOT / 'evals/generation/phase5/live_report.json')
    protected['configs/generation_ollama.json'] = sha(ROOT / 'configs/generation_ollama.json')
    for path in (ROOT / 'data/processed/sec_company_facts').rglob('*.json'):
        protected[str(path.relative_to(ROOT))] = sha(path)
    assert all(sha(ROOT / p) == h for p, h in protected.items())
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.live and any((OUTPUT / (qid + '.json')).exists() for qid in IDS):
        raise ValueError('Live results already exist; refusing regeneration')
    orchestrator = Orchestrator(document_tool(SECSectionRetriever(ROOT, config['retrieval']), config['retrieval']), financial_tool(LocalFinancialData.from_cache_dir(ROOT / 'data/processed/sec_company_facts')))
    questions = {r['question_id']: r for r in json.loads((ROOT / 'evals/phase5_demonstration.json').read_text())['questions']}
    prepared = []
    for qid in IDS:
        row = questions[qid]
        started = time.perf_counter()
        orchestration = orchestrator.execute(row['question'])
        assert orchestration['selected_tools'] == row['expected_routing']
        for result in orchestration['tool_results']:
            if result['tool_name'] == 'document_retrieval':
                assert len(result['evidence']) <= config['retrieval']['top_k']
        # top_k caps document chunks, not the independent structured financial fact.
        # Preserve the unchanged top-five retrieval plus its financial context.
        contexts = evidence_contexts(orchestration)
        prompt = build_prompt(Question(qid, row['question']), contexts, config['prompt'])
        trace = {'question_id': qid, 'question': row['question'], 'orchestration': orchestration,
                 'routing_matches': True, 'contexts': contexts, 'prompt': prompt,
                 'schema': SCHEMA, 'config': deepcopy(config), 'prompt_sha256': digest(prompt),
                 'preparation_latency_seconds': time.perf_counter() - started}
        prepared.append(trace)
        write_json(OUTPUT / (qid + '.prepared.json'), trace)
    if not args.live:
        print('Prepared exactly two demonstrations; no model calls.')
        return
    provider = create_provider(llm.provider)
    try:
        for trace in prepared:
            path = OUTPUT / (trace['question_id'] + '.json')
            trace.update(status='pending', raw_model_output=None, parsed_answer=None,
                         citations=[], citation_validation=[], token_usage=None, error=None,
                         structured_output_valid=False)
            # Persist before the one allowed call, so interruptions cannot trigger
            # silent repeat execution on a later invocation.
            write_json(path, trace)
            started = time.perf_counter()
            try:
                response = provider.generate(deepcopy(trace['prompt']), deepcopy(SCHEMA), llm)
                trace.update(raw_model_output=response.text, token_usage=response.usage,
                             provider_metadata=response.metadata, finish_status=response.finish_status)
                if response.finish_status != 'completed':
                    trace['status'] = 'incomplete_output'
                else:
                    parsed = validate_output(response.text, trace['contexts'])
                    trace['structured_output_valid'] = True
                    validation = validate_citation_grounding(parsed, trace['contexts'], trace['contexts'])
                    trace.update(status='success', parsed_answer=parsed, citations=parsed['citations'], citation_validation=validation)
            except ProviderError as error:
                trace.update(status='provider_error', error={'code': error.code})
            except ValueError as error:
                trace.update(status='invalid_output', error={'detail': str(error)})
            trace['generation_latency_seconds'] = time.perf_counter() - started
            trace['latency_seconds'] = trace['preparation_latency_seconds'] + trace['generation_latency_seconds']
            write_json(path, trace)
            print(trace['question_id'], trace['status'], flush=True)
    finally:
        verify_protected(ROOT, manifest)
        unchanged = all(sha(ROOT / p) == h for p, h in protected.items())
        write_json(OUTPUT / 'preservation_audit.json', {'unchanged': unchanged, 'sha256': protected,
                    'benchmark_sha256': sha(ROOT / 'evals/ground_truth/sec_retrieval_benchmark.json')})
        assert unchanged


if __name__ == '__main__':
    main()
