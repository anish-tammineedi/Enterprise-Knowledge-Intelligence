from collections import Counter, defaultdict
import math
import re
import unicodedata

import numpy as np


TOKENIZER_VERSION = 'sec_conservative_v1'
TOKEN = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|[\w]+(?:[.\-'’][\w]+)*%?", re.UNICODE)


def tokenize(text):
    normalized = unicodedata.normalize('NFKC', text).casefold()
    normalized = normalized.translate(str.maketrans({'’': "'", '‐': '-', '‑': '-'}))
    return [token.replace(',', '') if token[0].isdigit() else token for token in TOKEN.findall(normalized)]


class BM25:
    def __init__(self, texts, ids, k1=1.2, b=0.75):
        if not math.isfinite(k1) or k1 <= 0 or not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError('Invalid BM25 parameters')
        if not texts or len(texts) != len(ids) or len(set(ids)) != len(ids):
            raise ValueError('Invalid BM25 document alignment')
        self.ids = list(ids)
        self.k1, self.b = k1, b
        self.lengths = np.asarray([len(tokenize(text)) for text in texts], dtype=np.float64)
        self.average_length = float(self.lengths.mean())
        postings = defaultdict(list)
        for index, text in enumerate(texts):
            for token, frequency in sorted(Counter(tokenize(text)).items()):
                postings[token].append((index, frequency))
        self.postings = {token: (np.asarray([i for i, _ in pairs]), np.asarray([f for _, f in pairs], dtype=np.float64))
                         for token, pairs in sorted(postings.items())}

    def rank(self, query):
        scores = np.zeros(len(self.ids), dtype=np.float64)
        if self.average_length:
            norm = self.k1 * (1 - self.b + self.b * self.lengths / self.average_length)
            for token in sorted(set(tokenize(query))):
                if token not in self.postings:
                    continue
                indices, frequencies = self.postings[token]
                idf = math.log1p((len(self.ids) - len(indices) + 0.5) / (len(indices) + 0.5))
                scores[indices] += idf * frequencies * (self.k1 + 1) / (frequencies + norm[indices])
        return np.lexsort((np.asarray(self.ids), -scores)), scores


def reciprocal_rank_fusion(rankings, constant=60, candidate_depth=None):
    if not math.isfinite(constant) or constant < 0:
        raise ValueError('Invalid RRF constant')
    if candidate_depth is not None and (isinstance(candidate_depth, bool) or not isinstance(candidate_depth, int) or candidate_depth < 1):
        raise ValueError('Invalid candidate depth')
    scores = defaultdict(float)
    if not rankings:
        raise ValueError('At least one ranking is required')
    for ranking in rankings:
        if len(set(ranking)) != len(ranking):
            raise ValueError('Duplicate candidates in ranking')
        for rank, identifier in enumerate(ranking[:candidate_depth], 1):
            scores[identifier] += 1 / (constant + rank)
    order = sorted(scores, key=lambda identifier: (-scores[identifier], identifier))
    return order, dict(scores)
