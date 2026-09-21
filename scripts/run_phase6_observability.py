import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.generation.retrieval import verify_protected
from src.observability.aggregate import aggregate
from src.observability.historical import import_phase4b, import_phase5
from src.observability.trace import save_trace


def report(summary, groups, traces):
    def rate(metric):
        return 'unavailable' if metric['value'] is None else f"{metric['value']:.2%} ({metric['numerator']}/{metric['denominator']}; {metric['unavailable']} unavailable)"
    lines = ['# Phase 6 historical evaluation and observability', '',
             'No generation or network calls were made. This selection includes the 20 Phase 4B evaluated executions and the four final Phase 5 executions. Superseded Phase 5 runs and unrelated Phase 4A failures are excluded. Existing source artifacts are unchanged.', '',
             '## Aggregate metrics', '', '| Metric | Phase 4B | Phase 5 | Combined |', '|---|---|---|---|']
    for key in ('routing_success_rate', 'tool_success_rate', 'retrieval_evidence_sufficiency_rate', 'structured_output_validity', 'output_contract_validity', 'abstention_rate', 'expected_abstention_accuracy', 'abstention_label_accuracy', 'citation_validation_rate'):
        lines.append('| ' + key + ' | ' + ' | '.join(rate(g[key]) for g in (groups['phase4b'], groups['phase5'], summary)) + ' |')
    lines += ['', 'Sufficiency is not inferred from nonempty retrieval. Phase 4B uses coverage of every required benchmark evidence ID under the existing overlap matcher; this is a benchmark-coverage proxy, not proof that an answer is supported. Phase 5 reuses the saved reviewed sufficiency labels. They are also separated by basis in aggregate JSON. Unanswerable benchmark questions have no positive evidence-sufficiency target.', '',
              'Structured-output validity measures JSON fields and types. Output-contract validity also checks citations and abstention rules. Citation validity is syntactic membership/provenance validation, not semantic claim entailment. Valid abstentions with no citations count as citation-valid.', '',
              'Expected-abstention accuracy uses only cases labeled as requiring abstention. Abstention-label accuracy compares both positive and negative labels. Phase 4B labels reflect benchmark answerability; Phase 5 labels reflect the reviewed returned evidence, so the combined rate mixes those two evaluation scopes.', '',
              '## Latencies and tokens', '', '| Stage | Known samples | Mean seconds | Median seconds | p95 seconds |', '|---|---:|---:|---:|---:|']
    for key in ('end_to_end','retrieval','generation'):
        d=summary['latency_seconds'][key]
        lines.append('| '+key+' | '+str(d['count'])+' | '+' | '.join('unavailable' if d[k] is None else f'{d[k]:.6f}' for k in ('mean','median','p95'))+' |')
    lines += ['', 'Only the two new Phase 5 financial executions have recorded timing spanning orchestration, preparation, generation, and validation. The other 22 end-to-end latencies remain unavailable. All 24 recorded generation-pipeline durations are preserved by their actual scope in aggregate JSON. Historical Phase 5 retrieval latency was not separately timed; document-tool latency remains available as tool timing, not mislabeled retrieval timing. Historical routing and validation-stage times and timestamps are unavailable. p95 uses nearest rank.', '', '| Tokens | Known sum | Known mean | Missing executions |', '|---|---:|---:|---:|']
    for key,value in summary['tokens'].items():
        lines.append(f"| {key} | {value['known_sum']} | {value['known_mean']} | {value['unavailable']} |")
    lines += ['', 'All-query totals/averages become null if any execution has unknown token usage. Known sums and coverage remain available. Input/output totals may determine total_tokens when the provider did not report it; conflicting supplied totals are unavailable.', '', '## Failure attribution', '', '| Category | Primary | All occurrences |', '|---|---:|---:|']
    for key,value in summary['primary_failure_counts'].items():
        lines.append(f"| {key} | {value} | {summary['all_failure_counts'][key]} |")
    lines += ['', 'Primary attribution is exclusive and uses documented precedence. All occurrences preserve simultaneous failures; their counts need not sum to total queries. The combined Phase 5 execution remains partial_evidence plus generation_failure, citation_failure, and invalid_output. Earlier heuristic attributions are retained under lower_level.legacy_evaluation and are not silently promoted to measured semantic correctness.', '', '## Selected executions', '', '| Query ID | Source | Primary attribution | Output contract | Trace |', '|---|---|---|---|---|']
    for t in sorted(traces,key=lambda t:(t['source']['kind'],t['query']['id'])):
        lines.append(f"| {t['query']['id']} | {t['source']['kind']} | {t['failure_attribution']['primary']} | {t['validation']['output_contract_valid']} | [JSON](traces/{t['trace_id']}.json) |")
    lines += ['', '## Privacy and limits', '',
              'Query IDs identify the source questions. Unreviewed query text, prompts, evidence text, raw answers, arbitrary exception details, credentials, environment fields, and personal fields are not copied into unified logs. Only allowlisted operational configuration and SEC evidence metadata are retained. Approved public query text can be provided explicitly to the runtime privacy policy; names and addresses require that review because regex matching alone cannot guarantee PII removal.', '',
              'This is an offline historical evaluation, not a new model-quality experiment. Routing has labels only for Phase 5. Phase 4B has no routing/tool records. Semantic groundedness is not inferred from a valid JSON response or citation. Missing observations are null with explicit denominators, never zero-filled.']
    return '\n'.join(lines)+'\n'


def main(argv=None):
    parser=argparse.ArgumentParser(description='Offline unified trace ingestion and aggregation')
    parser.add_argument('--output',type=Path,default=ROOT/'evals/observability/phase6')
    parser.add_argument('--trace-dir',type=Path,help='Aggregate existing unified JSON traces instead of historical ingestion')
    args=parser.parse_args(argv)
    output=args.output.resolve()
    if output != (ROOT/'evals/observability/phase6').resolve() and output.is_relative_to(ROOT) and not output.is_relative_to(ROOT/'evals/observability'):
        raise ValueError('Output inside repository must be under evals/observability')
    if args.trace_dir:
        manifest_path=args.trace_dir.parent/'trace_manifest.json'
        paths=[args.trace_dir/(identity+'.json') for identity in json.loads(manifest_path.read_text())['trace_ids']] if manifest_path.exists() else sorted(args.trace_dir.glob('*.json'))
        traces=[json.loads(p.read_text()) for p in paths]
    else:
        traces=import_phase4b(ROOT)+import_phase5(ROOT)
    groups={kind:aggregate([t for t in traces if t['source']['kind']==kind]) for kind in sorted({t['source']['kind'] for t in traces})}
    summary=aggregate(traces)
    output.mkdir(parents=True,exist_ok=True)
    old_manifest=output/'trace_manifest.json'
    old_ids=json.loads(old_manifest.read_text())['trace_ids'] if old_manifest.exists() else []
    for trace in traces:
        save_trace(output/'traces'/(trace['trace_id']+'.json'),trace)
    current_ids=sorted({t['trace_id'] for t in traces})
    for identity in set(old_ids)-set(current_ids):
        if len(identity)==64 and all(c in '0123456789abcdef' for c in identity):
            (output/'traces'/(identity+'.json')).unlink(missing_ok=True)
    save_trace(output/'trace_manifest.json',{'trace_ids':current_ids})
    save_trace(output/'aggregate.json',{'overall':summary,'by_source':groups})
    if not args.trace_dir:
        (output/'report.md').write_text(report(summary,groups,traces))
    else:
        lines=['# Unified trace aggregate', '', f"Queries: {summary['total_queries']}", '', '| Metric | Value | Known denominator | Unavailable |', '|---|---:|---:|---:|']
        for key,value in summary.items():
            if isinstance(value,dict) and 'denominator' in value:
                lines.append(f"| {key} | {value['value']} | {value['denominator']} | {value['unavailable']} |")
        lines.extend(['', 'Latency and token statistics:', '', '```json', json.dumps({k:summary[k] for k in ('latency_seconds','tokens','primary_failure_counts')},indent=2), '```'])
        (output/'report.md').write_text('\n'.join(lines)+'\n')
    baseline_path=ROOT/'evals/observability/phase6/protected_before.json'
    before=json.loads(baseline_path.read_text())
    changed=[]
    historical_differences=[]
    for path, historical_sha256 in before.items():
        source=ROOT/path
        if not source.is_file():
            changed.append(path)
            continue
        current=source.read_bytes()
        current_sha256=hashlib.sha256(current).hexdigest()
        if current_sha256==historical_sha256:
            continue
        if path=='configs/dataset.json':
            reconstructed=current+b'\n'
            try:
                format_only=(hashlib.sha256(reconstructed).hexdigest()==historical_sha256 and
                             json.loads(reconstructed)==json.loads(current))
            except (UnicodeDecodeError, json.JSONDecodeError):
                format_only=False
            if format_only:
                historical_differences.append({
                    'path':path,
                    'historical_sha256':historical_sha256,
                    'final_sha256':current_sha256,
                    'classification':'one_trailing_newline_removed',
                    'historical_hash_reconstructed':True,
                    'parsed_json_values_identical':True,
                })
                continue
        changed.append(path)
    verify_protected(ROOT,json.loads((ROOT/'configs/generation_protected.json').read_text()))
    benchmark=hashlib.sha256((ROOT/'evals/ground_truth/sec_retrieval_benchmark.json').read_bytes()).hexdigest()
    assert benchmark=='74a2e70d531e389a47730e8c537329ec65cfae5134abec3739a9297feba47e86'
    save_trace(output/'protected_audit.json',{
        'verification_scope':'current_repository_check',
        'unchanged':not historical_differences and not changed,
        'checked_files':len(before),
        'historical_differences':historical_differences,
        'changed_files':changed,
        'final_state_verified':not changed,
        'benchmark_sha256':benchmark,
    })
    if changed:raise ValueError('Phase 1–5 artifacts changed')
    print(json.dumps({'total_queries':summary['total_queries'],'sources':{k:v['total_queries'] for k,v in groups.items()},'protected_files':len(before)},indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
