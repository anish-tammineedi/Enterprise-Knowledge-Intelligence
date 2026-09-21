from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from statistics import mean, median


VERSION = '2B.1'
STRATEGIES = ('fixed_size', 'recursive', 'sec_section')
PROVENANCE_FIELDS = (
    'company', 'ticker', 'cik', 'form', 'filing_date', 'report_date',
    'accession_number', 'source_url', 'document_id', 'local_path', 'source_sha256',
)
SEPARATORS = (r'\n\s*\n', r'\n', r'[.!?][\u201d\u2019"\x27)]*\s+', r'\s+')


@dataclass(frozen=True)
class ChunkingConfig:
    strategy: str
    chunk_size: int
    overlap: int
    min_chunk_size: int
    boundary_min_fraction: float

    def __post_init__(self):
        if self.strategy not in STRATEGIES:
            raise ValueError(f'Unknown strategy: {self.strategy}')
        for name in ('chunk_size', 'overlap', 'min_chunk_size'):
            if type(getattr(self, name)) is not int:
                raise ValueError(f'{name} must be an integer')
        if not 0 <= self.overlap < self.chunk_size:
            raise ValueError('Require 0 <= overlap < chunk_size')
        if not 1 <= self.min_chunk_size <= self.chunk_size:
            raise ValueError('Require 1 <= min_chunk_size <= chunk_size')
        if (isinstance(self.boundary_min_fraction, bool)
                or not isinstance(self.boundary_min_fraction, (int, float))
                or not 0 < self.boundary_min_fraction <= 1):
            raise ValueError('boundary_min_fraction must be in (0, 1]')

    @property
    def experiment_id(self):
        return digest({'version': VERSION, 'config': asdict(self)})


def digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def validate_document(document):
    for field in PROVENANCE_FIELDS:
        if not isinstance(document.get(field), str) or not document[field]:
            raise ValueError(f'Missing or invalid provenance: {field}')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', document['document_id']):
        raise ValueError('document_id must be safe for use as a filename')
    text = document.get('text')
    if not isinstance(text, str):
        raise ValueError('Document text must be a string')
    for collection in ('sections', 'content'):
        if not isinstance(document.get(collection), list):
            raise ValueError(f'{collection} must be a list')
        previous_end = 0
        section_ids = set()
        for entry in document[collection]:
            start, end = entry.get('start_char'), entry.get('end_char')
            if (type(start) is not int or type(end) is not int
                    or not previous_end <= start < end <= len(text)
                    or text[start:end] != entry.get('text')):
                raise ValueError(f'Invalid {collection} offsets or text')
            if collection == 'sections':
                for key in ('section_id', 'item', 'name'):
                    if not isinstance(entry.get(key), str) or not entry[key]:
                        raise ValueError(f'Missing section {key}')
                if entry['section_id'] in section_ids:
                    raise ValueError('Duplicate section_id')
                section_ids.add(entry['section_id'])
            previous_end = end


def natural_end(text, start, limit, minimum, level=0):
    if level == len(SEPARATORS):
        return limit
    candidates = [match.end() for match in re.finditer(SEPARATORS[level], text[start:limit])
                  if start + match.end() >= minimum]
    if candidates:
        return start + candidates[-1]
    return natural_end(text, start, limit, minimum, level + 1)


def split_spans(text, start, end, config):
    while start < end:
        limit = min(start + config.chunk_size, end)
        stop = limit
        if limit < end:
            minimum = start + max(config.overlap + 1,
                                  int(config.chunk_size * config.boundary_min_fraction))
            if config.strategy != 'fixed_size':
                stop = natural_end(text, start, limit, minimum)
            tail_length = end - stop + config.overlap
            if tail_length < config.min_chunk_size:
                target = min(config.min_chunk_size, (end - start + config.overlap) // 2)
                balanced = end - target + config.overlap
                if start + config.overlap < balanced <= limit:
                    stop = balanced
        yield start, stop
        if stop == end:
            break
        start = stop - config.overlap


def regions(document):
    text = document['text']
    cursor = 0
    for section in document['sections']:
        if text[cursor:section['start_char']].strip():
            yield cursor, section['start_char'], None
        yield section['start_char'], section['end_char'], section
        cursor = section['end_char']
    if text[cursor:].strip():
        yield cursor, len(text), None


def section_references(document, start, end):
    return [
        {'section_id': section['section_id'], 'item': section['item'],
         'section_name': section['name'], 'start_char': max(start, section['start_char']),
         'end_char': min(end, section['end_char'])}
        for section in document['sections']
        if section['start_char'] < end and section['end_char'] > start
    ]


def chunk_document(document, config):
    validate_document(document)
    text = document['text']
    parsed_hash = digest(document)
    units = regions(document) if config.strategy == 'sec_section' else [(0, len(text), None)]
    provenance = {field: document[field] for field in PROVENANCE_FIELDS}
    provenance['source_document_id'] = document['document_id']
    tables = [(index, block) for index, block in enumerate(document['content'])
              if block['type'] == 'table']
    chunks = []
    for unit_index, (unit_start, unit_end, section) in enumerate(units):
        for unit_chunk_index, (start, end) in enumerate(split_spans(text, unit_start, unit_end, config)):
            references = section_references(document, start, end)
            single = references[0] if len(references) == 1 else None
            unsectioned = end - start - sum(s['end_char'] - s['start_char'] for s in references)
            if unsectioned:
                single = None
            table_fragments = [
                {'block_index': index, 'block_start_char': block['start_char'],
                 'block_end_char': block['end_char'], 'start_char': max(start, block['start_char']),
                 'end_char': min(end, block['end_char']),
                 'is_partial': start > block['start_char'] or end < block['end_char']}
                for index, block in tables if block['start_char'] < end and block['end_char'] > start
            ]
            chunk_index = len(chunks)
            identity = {'version': VERSION, 'experiment_id': config.experiment_id,
                        'parsed_document_sha256': parsed_hash, 'document_id': document['document_id'],
                        'chunk_index': chunk_index, 'start_char': start, 'end_char': end}
            chunks.append({
                **provenance, **identity, 'chunk_id': digest(identity), 'strategy': config.strategy,
                'item': single['item'] if single else None,
                'section_name': single['section_name'] if single else None,
                'section_id': single['section_id'] if single else None,
                'section_scope': 'single' if single else 'mixed' if references else 'unsectioned',
                'sections': references, 'unsectioned_characters': unsectioned,
                'unit_index': unit_index, 'unit_chunk_index': unit_chunk_index,
                'overlap_with_previous': max(0, chunks[-1]['end_char'] - start) if chunks else 0,
                'text': text[start:end], 'character_count': end - start,
                'table_fragments': table_fragments,
            })
    return chunks


def summarize(chunks, config):
    lengths = [chunk['character_count'] for chunk in chunks]
    distribution = Counter()
    for chunk in chunks:
        distribution.update(set(section['item'] for section in chunk['sections']))
        if chunk['unsectioned_characters']:
            distribution['unsectioned'] += 1
    return {
        'total_chunks': len(chunks),
        'average_characters': round(mean(lengths), 2) if lengths else 0,
        'median_characters': median(lengths) if lengths else 0,
        'minimum_characters': min(lengths, default=0),
        'maximum_characters': max(lengths, default=0),
        'very_small_threshold': config.min_chunk_size,
        'very_small_chunks': sum(length < config.min_chunk_size for length in lengths),
        'section_distribution': dict(sorted(distribution.items())),
        'mixed_section_chunks': sum(len(chunk['sections']) > 1 for chunk in chunks),
        'chunks_with_tables': sum(bool(chunk['table_fragments']) for chunk in chunks),
        'chunks_with_partial_tables': sum(any(t['is_partial'] for t in chunk['table_fragments'])
                                         for chunk in chunks),
        'total_chunk_characters_including_overlap': sum(lengths),
    }


def write_json(path, value):
    path = Path(path)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == payload:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(payload, encoding='utf-8')
    temporary.replace(path)


def generate_experiment(documents, config, output_dir):
    if not documents:
        raise ValueError('No parsed documents found')
    documents = sorted(documents, key=lambda document: document['document_id'])
    ids = [document['document_id'] for document in documents]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate source document IDs')
    for document in documents:
        validate_document(document)
    manifest = [{'document_id': document['document_id'], 'parsed_document_sha256': digest(document)}
                for document in documents]
    corpus_id = digest(manifest)
    destination = Path(output_dir) / config.strategy / config.experiment_id[:16] / corpus_id[:16]
    all_chunks = []
    by_filing = {}
    for document in documents:
        chunks = chunk_document(document, config)
        all_chunks.extend(chunks)
        by_filing[document['document_id']] = summarize(chunks, config)
        write_json(destination / f"{document['document_id']}.json", {
            'version': VERSION, 'config': asdict(config), 'experiment_id': config.experiment_id,
            'corpus_id': corpus_id, 'source_document_id': document['document_id'], 'chunks': chunks,
        })
    summary = {'version': VERSION, 'config': asdict(config), 'experiment_id': config.experiment_id,
               'corpus_id': corpus_id, 'documents': manifest, 'filing_count': len(documents),
               **summarize(all_chunks, config), 'per_filing': by_filing}
    write_json(destination / 'summary.json', summary)
    return destination, summary
