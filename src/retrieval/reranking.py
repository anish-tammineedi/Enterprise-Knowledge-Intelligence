from importlib.metadata import version
import json
import math
from pathlib import Path
import time

import numpy as np

from src.embeddings.local_dense import digest, write_json
from src.evaluation.dense_metrics import evaluate_question


class LocalReranker:
    def __init__(self, config, model_cache):
        self.config = config
        self.model_cache = Path(model_cache)
        self.model = None
        self.signature = {'implementation': 'cross_encoder_logits_v1', **config,
                          'versions': {name: version(name) for name in ['sentence-transformers', 'transformers', 'torch', 'numpy']}}
        self.load_seconds = 0

    def load(self):
        if self.model is None:
            start = time.perf_counter()
            import torch
            from sentence_transformers import CrossEncoder
            torch.manual_seed(self.config['seed'])
            torch.set_num_threads(self.config['threads'])
            torch.use_deterministic_algorithms(True)
            snapshot = self.model_cache / ('models--' + self.config['name'].replace('/', '--')) / 'snapshots' / self.config['revision']
            if not (snapshot / 'model.safetensors').exists():
                raise FileNotFoundError('Download the pinned reranker snapshot first')
            self.model = CrossEncoder(str(snapshot), max_length=self.config['max_length'], device=self.config['device'],
                                      local_files_only=True, trust_remote_code=False, activation_fn=torch.nn.Identity())
            self.model.model.eval()
            self.load_seconds = time.perf_counter() - start
        return self.model

    def score(self, pairs):
        model = self.load()
        started = time.perf_counter()
        scores = np.asarray(model.predict(pairs, batch_size=self.config['batch_size'], show_progress_bar=False,
                                          convert_to_numpy=True), dtype=float).reshape(-1)
        elapsed = time.perf_counter() - started
        full = model.tokenizer([p[0] for p in pairs], [p[1] for p in pairs], truncation=False, verbose=False)
        limited = model.tokenizer([p[0] for p in pairs], [p[1] for p in pairs], truncation='longest_first',
                                  max_length=self.config['max_length'], return_offsets_mapping=True)
        diagnostics = []
        for i, tokens in enumerate(full['input_ids']):
            offsets = limited['offset_mapping'][i]
            seq = limited.sequence_ids(i)
            end = max((b for (_, b), segment in zip(offsets, seq) if segment == 1), default=0)
            diagnostics.append({'input_tokens': len(tokens), 'truncated': len(tokens) > self.config['max_length'],
                                'encoded_chunk_end_char': end})
        return scores, diagnostics, elapsed


class PairScoreCache:
    def __init__(self, directory):
        self.directory = Path(directory)

    def score(self, question, chunks, scorer):
        entries, missing = {}, []
        if len({c['chunk_id'] for c in chunks}) != len(chunks):
            raise ValueError('Duplicate candidates')
        for chunk in chunks:
            identity = {'model': scorer.signature, 'question': question, 'chunk_id': chunk['chunk_id'], 'text_sha256': digest(chunk['text'])}
            path = self.directory / digest(scorer.signature) / (digest(identity) + '.json')
            try:
                entry = json.loads(path.read_text())
                if entry['identity'] != identity or not math.isfinite(entry['score']) or entry['payload_sha256'] != digest({k: v for k, v in entry.items() if k != 'payload_sha256'}):
                    raise ValueError('Invalid cache entry')
                entries[chunk['chunk_id']] = entry
            except (OSError, ValueError, KeyError, TypeError):
                missing.append((chunk, identity, path))
        inference_seconds = 0
        for offset in range(0, len(missing), scorer.signature['batch_size']):
            batch = missing[offset:offset + scorer.signature['batch_size']]
            scores, diagnostics, elapsed = scorer.score([(question, c['text']) for c, _, _ in batch])
            if len(scores) != len(batch) or len(diagnostics) != len(batch) or not np.isfinite(scores).all():
                raise ValueError('Cross-encoder score alignment failure')
            inference_seconds += elapsed
            for (chunk, identity, path), score, detail in zip(batch, scores, diagnostics):
                entry = {'identity': identity, 'score': float(score), 'diagnostics': detail,
                         'amortized_inference_seconds': elapsed / len(batch)}
                entry['payload_sha256'] = digest(entry)
                write_json(path, entry)
                entries[chunk['chunk_id']] = entry
        return entries, {'hits': len(chunks) - len(missing), 'misses': len(missing), 'inference_seconds': inference_seconds}


def rerank(candidates, scores, depth):
    if isinstance(depth, bool) or not isinstance(depth, int) or depth <= 0:
        raise ValueError('Invalid candidate depth')
    pool = candidates[:depth]
    if len({c['chunk_id'] for c in pool}) != len(pool):
        raise ValueError('Duplicate candidates')
    if any(c['chunk_id'] not in scores or not math.isfinite(scores[c['chunk_id']]['score']) for c in pool):
        raise ValueError('Missing or invalid pair score')
    enriched = [{**c, 'original_retrieval_rank': c['rank'], 'original_retrieval_system': c['score_type'],
                 'reranker_score': scores[c['chunk_id']]['score'],
                 'reranker_diagnostics': scores[c['chunk_id']]['diagnostics']} for c in pool]
    enriched.sort(key=lambda c: (-c['reranker_score'], c['chunk_id']))
    return [dict(c, rank=i) for i, c in enumerate(enriched, 1)]


def analyze(question, candidates, reranked, policy, ks=(1, 3, 5, 10)):
    original, original_matches = evaluate_question(question, candidates, list(ks), policy)
    metrics, matches = evaluate_question(question, reranked, list(ks), policy)
    available = set(original['oracle_matchable_evidence'])
    required = {e['evidence_id'] for e in question['evidence']}
    recovered = set(metrics['recovered_evidence@10'])
    missing_pool, missing_ranking = required - available, available - recovered
    relevant_ids = {c['chunk_id'] for c, found in zip(candidates, original_matches) if found}
    before = {c['chunk_id']: i for i, c in enumerate(candidates, 1)}
    after = {c['chunk_id']: i for i, c in enumerate(reranked, 1)}
    movement = {f'promoted_into_top{k}': sorted(i for i in relevant_ids if before[i] > k and after[i] <= k) for k in [1, 3, 5]}
    movement['demoted_out_of_top5'] = sorted(i for i in relevant_ids if before[i] <= 5 and after[i] > 5)
    required_docs = {d['document_id'] for d in question['required_documents']}
    available_docs = {e['document_id'] for e in question['evidence'] if e['evidence_id'] in available}
    return metrics, matches, {
        'oracle_evidence_recall': len(available) / len(required), 'oracle_any_evidence': bool(available),
        'oracle_all_evidence': required <= available, 'oracle_all_documents': required_docs <= available_docs,
        'missing_from_pool': sorted(missing_pool), 'available_but_missed_at10': sorted(missing_ranking),
        'failure_class': ('both' if missing_pool and missing_ranking else 'candidate_generation' if missing_pool else 'reranking' if missing_ranking else 'complete'),
        'movement': movement, 'recall_delta': {str(k): metrics[f'recall@{k}'] - original[f'recall@{k}'] for k in ks},
        'reciprocal_rank_delta_within_pool': metrics['reciprocal_rank'] - original['reciprocal_rank']}
