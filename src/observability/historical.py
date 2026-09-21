import hashlib
import json
from pathlib import Path

from src.evaluation.dense_metrics import match_evidence
from src.observability.trace import Privacy, classify, make_trace


def read(path):
    return json.loads(Path(path).read_text())


def import_phase4b(root, privacy=None):
    root = Path(root)
    privacy = privacy or Privacy()
    results = read(root / 'evals/generation/phase4b/results.json')['results']
    questions = {r['question_id']: r for r in read(root / 'evals/generation/phase4b/subset.json')['questions']}
    candidates = [(p, read(p)) for p in sorted((root / 'evals/generation/phase4a_ollama/traces').glob('*.json'))]
    out = []
    for result in sorted(results, key=lambda r: r['question_id']):
        matches = [(p, t) for p, t in candidates if all(t.get(k) == result.get(k) for k in ('question_id', 'status', 'raw_model_output', 'latency_seconds'))]
        if len(matches) != 1:
            raise ValueError('Historical trace match must be unique')
        path, generation = matches[0]
        q = questions[result['question_id']]
        required = {e['evidence_id'] for e in q.get('evidence', [])}
        matched = {e['evidence_id'] for c in generation.get('contexts', []) for e in q.get('evidence', [])
                   if match_evidence(c, e, {'minimum_nonwhitespace_characters': 32, 'minimum_evidence_fraction': 0.5})}
        sufficient = required <= matched if q['answerable'] and required else None
        labels = {'expected_abstention': not q['answerable'], 'document_evidence_sufficient': sufficient,
                  'sufficiency_basis': 'benchmark_required_evidence_coverage' if sufficient is not None else None,
                  'legacy_attribution': result.get('attribution'), 'evidence_sufficient': sufficient}
        trace = make_trace(str(path.relative_to(root)), q['question'], generation['config'], generation=generation,
                           labels=labels, privacy=privacy, source_kind='phase4b')
        trace['query']['id'] = q['question_id']
        trace['source']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        trace['retrieval']['required_evidence_ids'] = sorted(required)
        trace['retrieval']['matched_evidence_ids'] = sorted(matched)
        trace['lower_level']['legacy_evaluation'] = {k: result.get(k) for k in ('attribution', 'retrieval_evidence_present', 'citation_validity', 'citation_precision', 'citation_recall', 'correctness', 'groundedness_heuristic')}
        out.append(trace)
    return out


def import_phase5(root, privacy=None):
    root = Path(root)
    privacy = privacy or Privacy()
    final = read(root / 'evals/generation/phase5/final_summary.json')
    originals = {r['question_id']: r for r in read(root / 'evals/generation/phase5/live_report.json')['questions']}
    expected = {r['question_id']: r['expected_routing'] for r in read(root / 'evals/phase5_demonstration.json')['questions']}
    out = []
    for row in sorted(final['results'], key=lambda r: r['question_id']):
        path = root / row['trace_path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['trace_sha256']:
            raise ValueError('Phase 5 source trace hash mismatch')
        generation = read(path)
        orchestration = generation.get('orchestration', originals[row['question_id']]['orchestration'])
        labels = {'expected_tools': expected[row['question_id']],
                  'expected_abstention': not row['evidence_sufficient'],
                  'document_evidence_sufficient': row['document_evidence_sufficient'],
                  'sufficiency_basis': 'saved_phase5_review' if row['document_evidence_sufficient'] is not None else None,
                  'evidence_sufficient': row['evidence_sufficient'], 'claims_supported': row['every_factual_claim_supported'],
                  'legacy_attribution': row['final_status']}
        trace = make_trace(row['trace_path'], row['question'], generation['config'], orchestration, generation,
                           labels, privacy=privacy, source_kind='phase5')
        trace['lower_level']['evidence_adapter_latency_seconds'] = generation.get('retrieval_latency_seconds')
        trace['retrieval']['latency_seconds'] = None
        trace['retrieval']['latency_source'] = None
        trace['query']['id'] = row['question_id']
        trace['source']['sha256'] = row['trace_sha256']
        trace['source']['selection'] = row['execution']
        trace['lower_level']['legacy_evaluation'] = {'final_status': row['final_status'],
            'generation_correct': row['generation_correct'], 'citation_correct': row['citation_correct']}
        trace['latency']['recorded_scope'] = 'preparation_and_generation_including_orchestration' if row['execution'] == 'new_once' else 'generation_pipeline_excluding_orchestration'
        if row['execution'] == 'new_once':
            trace['latency']['end_to_end_seconds'] = trace['latency']['recorded_seconds']
        out.append(classify(trace))
    return out
