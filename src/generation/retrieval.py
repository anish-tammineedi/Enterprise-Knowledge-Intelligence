import json
from pathlib import Path

import numpy as np

from scripts.run_dense_retrieval import load_chunks
from src.embeddings.local_dense import SentenceEncoder, file_sha256
from src.retrieval.dense import cosine_ranking
from src.retrieval.lexical import BM25, reciprocal_rank_fusion


def verify_protected(root, manifest):
    root = Path(root)
    current = {str(p.relative_to(root)) for directory in manifest['roots'] for p in (root / directory).rglob('*') if p.is_file()}
    if current != set(manifest['sha256']):
        raise ValueError('Protected artifact inventory changed')
    if any(file_sha256(root / path) != value for path, value in manifest['sha256'].items()):
        raise ValueError('Protected artifact content changed')


class SECSectionRetriever:
    def __init__(self, root, config):
        self.root = Path(root)
        self.config = config
        self.dense_path = self.root / config['dense_run']
        original = json.loads((self.dense_path / 'experiment.json').read_text())
        self.dense_config = original['config']
        documents = {d['document_id']: d for d in (json.loads(p.read_text()) for p in (self.root / self.dense_config['parsed_dir']).glob('*.json'))}
        self.chunks, _ = load_chunks(self.root / self.dense_config['chunk_dirs']['sec_section'], 'sec_section', documents)
        self.ids = [c['chunk_id'] for c in self.chunks]
        lexical = json.loads((self.root / config['lexical_config']).read_text())
        self.fusion = lexical['rrf']
        self.bm25 = BM25([c['text'] for c in self.chunks], self.ids, lexical['bm25']['k1'], lexical['bm25']['b'])
        self.matrix = None

    def _query_embedding(self, question):
        if self.matrix is None:
            self.matrix = np.load(self.dense_path / 'sec_section/embeddings.npy', allow_pickle=False)
            manifest = json.loads((self.dense_path / 'sec_section/index_manifest.json').read_text())
            if len(manifest) != len(self.chunks) or self.matrix.shape != (len(self.chunks), self.dense_config['model']['dimensions']):
                raise ValueError('Dense matrix alignment mismatch')
            for i, (entry, chunk) in enumerate(zip(manifest, self.chunks)):
                if entry['embedding_row'] != i or any(entry[key] != value for key, value in chunk.items()):
                    raise ValueError('Dense manifest alignment mismatch')
            self.queries = np.load(self.dense_path / 'query_embeddings.npy', allow_pickle=False)
            self.query_manifest = json.loads((self.dense_path / 'query_manifest.json').read_text())
            if len(self.queries) != len(self.query_manifest):
                raise ValueError('Query manifest alignment mismatch')
        for i, row in enumerate(self.query_manifest):
            if row['embedding_row'] != i:
                raise ValueError('Query row alignment mismatch')
            if row['text'] == question:
                return self.queries[i]
        encoder = SentenceEncoder(self.dense_config['model'], self.root / self.dense_config['model_cache'])
        vectors, _ = encoder.encode([question], 'query')
        return vectors[0]

    def retrieve(self, question, mode, top_k):
        if not isinstance(question, str) or not question.strip() or mode not in ['bm25', 'hybrid']:
            raise ValueError('Invalid retrieval request')
        if type(top_k) is not int or not 1 <= top_k <= len(self.chunks):
            raise ValueError('Invalid context top K')
        order, scores = self.bm25.rank(question)
        score_type = 'bm25'
        if mode == 'hybrid':
            dense_order, _ = cosine_ranking(self._query_embedding(question), self.matrix, self.ids)
            fused, fused_scores = reciprocal_rank_fusion([[self.ids[i] for i in dense_order], [self.ids[i] for i in order]], **self.fusion)
            positions = {identifier: i for i, identifier in enumerate(self.ids)}
            order = [positions[identifier] for identifier in fused]
            scores = np.asarray([fused_scores[identifier] for identifier in self.ids])
            score_type = 'rrf'
        return [{**self.chunks[i], 'retrieval_rank': rank, 'retrieval_score': float(scores[i]),
                 'retrieval_score_type': score_type} for rank, i in enumerate(order[:top_k], 1)]
