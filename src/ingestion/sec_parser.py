import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


ITEM_ORDER = '1 1A 1B 1C 2 3 4 5 6 7 7A 8 9 9A 9B 9C 10 11 12 13 14 15 16'.split()
TITLE_PREFIXES = dict(zip(ITEM_ORDER, [
    'Business', 'Risk Factors', 'Unresolved Staff Comments', 'Cybersecurity',
    'Properties', 'Legal Proceedings', 'Mine Safety', 'Market for Registrant',
    '[Reserved]|Reserved|Selected Financial Data', 'Management', 'Quantitative',
    'Financial Statements', 'Changes in and Disagreements', 'Controls and Procedures',
    'Other Information', 'Disclosure Regarding Foreign', 'Directors',
    'Executive Compensation', 'Security Ownership', 'Certain Relationships',
    'Principal Accountant', 'Exhibits?|Exhibit and Financial', 'Form 10-K Summary',
]))
BLOCK_TAGS = {'div', 'p', 'section', 'article', 'header', 'footer', 'li', 'ul', 'ol',
              'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre'}
ITEM_RE = re.compile(r'^item\s+(\d{1,2}[ABC]?)\s*[.\-–—:]?\s+(.+)$', re.I)
HIDDEN_RE = re.compile(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\s*(?:!important\s*)?(?:;|$)', re.I)


def normalize(text):
    return re.sub(r'\s+', ' ', text.replace('\u200b', '').replace('\ufeff', '').replace('\xad', '')).strip()


def heading(text):
    match = ITEM_RE.match(text)
    if not match or len(text) > 220:
        return None
    item, title = match.group(1).upper(), match.group(2).strip()
    prefix = TITLE_PREFIXES.get(item)
    if prefix and re.match('(?:' + prefix.replace('[Reserved]', r'\[Reserved\]') + ')', title, re.I):
        return item, title
    return None


def cell_text(node):
    if isinstance(node, NavigableString):
        return str(node)
    if node.name == 'br':
        return ' '
    value = ''.join(cell_text(child) for child in node.children)
    return ' ' + value + ' ' if node.name in BLOCK_TAGS or node.name in {'td', 'th', 'tr'} else value


def parse_html(raw, metadata):
    soup = BeautifulSoup(raw, 'html.parser')
    removed = 0
    for tag in list(soup.find_all(True)):
        if tag.decomposed or tag.name is None:
            continue
        if (tag.name in {'script', 'style', 'head', 'template', 'ix:header', 'ix:hidden'}
                or tag.has_attr('hidden') or HIDDEN_RE.search(tag.get('style', ''))):
            tag.decompose()
            removed += 1
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    for tag in list(soup.find_all(True)):
        if tag.name and tag.name.startswith('ix:'):
            tag.unwrap()
    blocks = []

    def emit(text, node, kind='paragraph', **extra):
        text = text.strip() if kind == 'table' else normalize(text)
        if text:
            blocks.append({'type': kind, 'text': text, 'html_id': node.get('id'), 'linked': bool(node.find('a', href=True)), **extra})

    def walk(node):
        pending = []

        def flush():
            emit(''.join(pending), node)
            pending.clear()

        for child in node.children:
            if isinstance(child, NavigableString):
                pending.append(str(child))
            elif isinstance(child, Tag):
                if child.name == 'table':
                    flush()
                    rows = []
                    for row in child.find_all('tr'):
                        if row.find_parent('table') is not child:
                            continue
                        cells = []
                        for cell in row.find_all(['td', 'th'], recursive=False):
                            cells.append({'text': normalize(cell_text(cell)),
                                          'colspan': cell.get('colspan', '1'),
                                          'rowspan': cell.get('rowspan', '1')})
                        if any(cell['text'] for cell in cells):
                            rows.append(cells)
                    emit('\n'.join(' | '.join(cell['text'] for cell in row) for row in rows),
                         child, 'table', rows=rows)
                elif child.name in BLOCK_TAGS:
                    flush()
                    walk(child)
                elif child.name == 'br':
                    flush()
                else:
                    pending.append(child.get_text('', strip=False))
        flush()

    walk(soup.body or soup)
    offset = 0
    for block in blocks:
        block['start_char'] = offset
        block['end_char'] = offset + len(block['text'])
        offset = block['end_char'] + 2
    text = '\n\n'.join(block['text'] for block in blocks)
    candidates = []
    for index, block in enumerate(blocks):
        found = heading(block['text']) if block['type'] != 'table' and not block['linked'] else None
        if found:
            candidates.append((index, *found))
    selected = []
    warnings = []
    for candidate in candidates:
        index, item, title = candidate
        if selected and ITEM_ORDER.index(item) <= ITEM_ORDER.index(selected[-1][1]):
            warnings.append(f'Ignored duplicate or out-of-order heading: Item {item} at block {index}')
            continue
        selected.append(candidate)
    sections = []
    doc_id = f"{metadata['ticker']}_{metadata['accession_number'].replace('-', '')}"
    for position, (index, item, title) in enumerate(selected):
        start = blocks[index]['start_char']
        end = blocks[selected[position + 1][0]]['start_char'] if position + 1 < len(selected) else len(text)
        section_text = text[start:end].rstrip()
        sections.append({'section_id': f'{doc_id}:item_{item}', 'item': item,
                         'name': title, 'heading': blocks[index]['text'],
                         'start_char': start, 'end_char': start + len(section_text),
                         'text': section_text})
    for item in ['1', '1A', '7', '8']:
        section = next((s for s in sections if s['item'] == item), None)
        if section is None or len(section['text']) < 500:
            warnings.append(f'Missing or unusually short core section: Item {item}')
    return {**metadata, 'document_id': doc_id, 'parser_version': '2A.1',
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'text': text, 'content': blocks, 'sections': sections,
            'statistics': {'source_bytes': len(raw), 'normalized_characters': len(text),
                           'word_count': len(text.split()), 'block_count': len(blocks),
                           'table_count': sum(b['type'] == 'table' for b in blocks),
                           'removed_element_count': removed, 'section_count': len(sections),
                           'heading_candidate_count': len(candidates), 'warnings': warnings}}


def parse_filing(metadata, root):
    return parse_html((Path(root) / metadata['local_path']).read_bytes(), metadata)


def save_document(document, output_dir):
    path = Path(output_dir) / f"{document['document_id']}.json"
    payload = json.dumps(document, ensure_ascii=False, indent=2) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding='utf-8') != payload:
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(payload, encoding='utf-8')
        temporary.replace(path)
    return path
