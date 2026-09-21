import hashlib
from importlib.metadata import version
import json
from pathlib import Path

import numpy as np


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == payload:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(payload, encoding='utf-8')
    temporary.replace(path)


def write_array(path, array):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if np.array_equal(np.load(path, allow_pickle=False), array):
                return
        except (OSError, ValueError, EOFError):
            pass
    temporary = path.with_suffix('.npy.tmp')
    with temporary.open('wb') as stream:
        np.save(stream, array, allow_pickle=False)
    temporary.replace(path)


class SentenceEncoder:
    def __init__(self, config, model_cache):
        self.config = config
        self.model_cache = Path(model_cache)
        self.model = None
        self.signature = {
            'implementation': 'sentence_transformers_normalized_v1', **config,
            'versions': {name: version(name) for name in ('sentence-transformers', 'transformers', 'torch', 'numpy')},
        }
        self.dimensions = config['dimensions']

    def load(self):
        if self.model is None:
            import torch
            from sentence_transformers import SentenceTransformer
            torch.manual_seed(self.config['seed'])
            torch.set_num_threads(self.config['threads'])
            torch.use_deterministic_algorithms(True)
            snapshot = self.model_cache / ('models--' + self.config['name'].replace('/', '--')) / 'snapshots' / self.config['revision']
            if not (snapshot / 'model.safetensors').exists():
                raise FileNotFoundError(f'Download the pinned model into {self.model_cache} first')
            self.model = SentenceTransformer(str(snapshot), device=self.config['device'],
                                             local_files_only=True, trust_remote_code=False)
            self.model.max_seq_length = self.config['max_sequence_length']
            self.model.eval()
            if self.model.get_sentence_embedding_dimension() != self.dimensions:
                raise ValueError('Embedding dimension differs from configuration')
        return self.model

    def encode(self, texts, role):
        model = self.load()
        prefix = self.config['query_prefix'] if role == 'query' else ''
        inputs = [prefix + text for text in texts]
        vectors = model.encode(inputs, batch_size=self.config['batch_size'], show_progress_bar=False,
                               convert_to_numpy=True, normalize_embeddings=True)
        full = model.tokenizer(inputs, truncation=False, padding=False)['input_ids']
        limited = model.tokenizer(inputs, truncation=True, padding=False,
                                  max_length=model.max_seq_length, return_offsets_mapping=True)['offset_mapping']
        diagnostics = [{'token_count': len(tokens), 'truncated': len(tokens) > model.max_seq_length,
                        'encoded_text_end_char': max(0, max(end for _, end in offsets) - len(prefix))}
                       for tokens, offsets in zip(full, limited)]
        return np.asarray(vectors, dtype=np.float32), diagnostics


class EmbeddingCache:
    def __init__(self, directory):
        self.directory = Path(directory)

    def encode(self, records, encoder, namespace, role='document'):
        ids = [record['id'] for record in records]
        if len(ids) != len(set(ids)) or not records:
            raise ValueError('Embedding records must be nonempty with unique IDs')
        if role not in {'document', 'query'} or Path(namespace).name != namespace:
            raise ValueError('Invalid embedding role or namespace')
        cache_dir = self.directory / digest(encoder.signature) / namespace
        vectors = [None] * len(records)
        metadata = [None] * len(records)
        missing = []
        for index, record in enumerate(records):
            identity = {'id': record['id'], 'text_sha256': digest(record['text']),
                        'encoder': encoder.signature, 'role': role}
            key = digest(identity)
            array_path = cache_dir / f'{key}.npy'
            metadata_path = cache_dir / f'{key}.json'
            try:
                entry = json.loads(metadata_path.read_text(encoding='utf-8'))
                vector = np.load(array_path, allow_pickle=False)
                if (entry['identity'] != identity or entry['array_sha256'] != file_sha256(array_path)
                        or vector.shape != (encoder.dimensions,) or not np.isfinite(vector).all()
                        or not np.isclose(np.linalg.norm(vector), 1, atol=1e-5)):
                    raise ValueError('Invalid cached vector')
                vectors[index], metadata[index] = vector, entry['diagnostics']
            except (OSError, ValueError, KeyError, EOFError):
                missing.append((index, identity, array_path, metadata_path))
        batch_size = encoder.signature['batch_size']
        for offset in range(0, len(missing), batch_size):
            batch = missing[offset:offset + batch_size]
            batch_vectors, diagnostics = encoder.encode([records[i]['text'] for i, *_ in batch], role)
            if batch_vectors.shape != (len(batch), encoder.dimensions) or len(diagnostics) != len(batch):
                raise ValueError('Encoder output is not aligned to input records')
            norms = np.linalg.norm(batch_vectors, axis=1)
            if not np.isfinite(batch_vectors).all() or np.any(norms == 0):
                raise ValueError('Encoder returned invalid vectors')
            batch_vectors = (batch_vectors / norms[:, None]).astype(np.float32)
            for (index, identity, array_path, metadata_path), vector, detail in zip(batch, batch_vectors, diagnostics):
                vectors[index], metadata[index] = vector, detail
                write_array(array_path, vector)
                write_json(metadata_path, {'identity': identity, 'diagnostics': detail,
                                           'array_sha256': file_sha256(array_path)})
            if offset % (batch_size * 8) == 0 or offset + batch_size >= len(missing):
                print(f'{namespace}: encoded {min(offset + batch_size, len(missing))}/{len(missing)} missing vectors', flush=True)
        return np.stack(vectors), metadata, {'hits': len(records) - len(missing), 'misses': len(missing)}
