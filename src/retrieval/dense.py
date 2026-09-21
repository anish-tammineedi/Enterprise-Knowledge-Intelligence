import numpy as np


def cosine_ranking(query, matrix, chunk_ids):
    query = np.asarray(query, dtype=np.float32)
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim != 2 or query.shape != (matrix.shape[1],) or len(chunk_ids) != len(matrix):
        raise ValueError('Invalid query/index alignment')
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError('Duplicate chunk IDs')
    norms = np.linalg.norm(matrix, axis=1)
    query_norm = np.linalg.norm(query)
    if not np.isfinite(matrix).all() or not np.isfinite(query).all() or query_norm == 0 or np.any(norms == 0):
        raise ValueError('Cosine similarity requires finite nonzero vectors')
    scores = np.clip((matrix @ query) / (norms * query_norm), -1, 1)
    order = np.lexsort((np.asarray(chunk_ids), -scores))
    return order, scores
