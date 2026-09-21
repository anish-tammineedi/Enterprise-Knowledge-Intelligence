# Phase 2B: metadata-aware chunking

## Run experiments

```bash
.venv/bin/python scripts/chunk_sec_filings.py
.venv/bin/python scripts/chunk_sec_filings.py --strategy sec_section
.venv/bin/python -m unittest discover -s tests -v
```

Edit `configs/chunking.json` or provide `--config path/to/experiment.json`. `--root` controls the base directory for relative paths. Repeat `--strategy` to select multiple configured strategies. Each experiment merges its settings over `defaults`; add multiple entries for a strategy to run different sizes or overlaps. All parsed JSON files in `input_dir` are loaded independently, sorted by document ID, and validated before an experiment writes output. Invalid input or an empty corpus returns a nonzero exit code.

## Configuration and strategies

All lengths and offsets use Python Unicode characters, not tokens or UTF-8 bytes. The checked-in initial configuration uses `chunk_size=2000`, `overlap=200`, `min_chunk_size=200`, and `boundary_min_fraction=0.5`. These are experiment parameters, not a claim of optimality.

- **Fixed size:** consecutive character windows, with exact configured overlap. A final small remainder can rebalance the preceding boundary while respecting the maximum size.
- **Recursive:** within each window, recursively search a separator hierarchy: paragraphs, line breaks (including table rows), sentence-ending punctuation plus whitespace, whitespace, and finally characters. Select the rightmost boundary of the first usable kind in the latter portion of the window. `boundary_min_fraction` controls the earliest preferred cut. This avoids emitting a tiny fragment merely because an early paragraph boundary exists.
- **SEC section-aware:** apply the recursive splitter separately inside each parsed section. Oversized sections retain their Item metadata on every chunk. Preambles and substantive unassigned gaps are split as separate unsectioned regions. Missing Items are not invented. Whitespace-only gaps between parsed sections are omitted; all non-whitespace source content is covered.

`chunk_size` is a hard maximum. `min_chunk_size` is a soft terminal-fragment target and the strict less-than threshold for very small chunk statistics. Rebalancing may use a character cut when needed. Existing short regions cannot be enlarged across section boundaries. Overlap is exact between adjacent chunks in one region and resets to zero at region boundaries. Chunk starts can therefore land inside words or table rows even when chunk ends prefer natural boundaries. No header text is prepended and no table headings are fabricated.

## Provenance and output layout

Every chunk contains company, ticker, CIK (`cik`), form, filing and report dates, accession, source URL, source document ID, original HTML path/hash, canonical parsed-document hash, chunk index, experiment identity, character offsets, and exact source text. `start_char` is inclusive and `end_char` exclusive in the parsed document’s `text`. Chunk indices are zero-based per filing; unit indices identify regions and local chunk positions.

`sections` lists every intersected Item, name, section ID, and clipped source span. Singular `item`, `section_name`, and `section_id` fields are populated only when the entire chunk lies inside one section. They are null for mixed or unsectioned chunks; `section_scope` distinguishes these cases. Global strategies may cross Items and include intervening separator whitespace. Section-aware chunks never cross Items.

Table-derived text stays in the exact source slices. `table_fragments` records the source content block index, full table bounds, intersected bounds, and whether only part of that table is present. It provides a link back to the parsed cells and span attributes. Long tables may span chunks; this phase does not interpret financial values or guarantee indivisible rows.

Files are written under `data/processed/chunks/<strategy>/<experiment hash prefix>/<corpus hash prefix>/`. The experiment identity includes the full configuration and algorithm version. The corpus identity includes sorted document IDs and canonical parsed-document hashes. Changing settings or inputs produces a separate directory. Chunk IDs are full SHA-256 digests of the experiment, parsed document, document ID, index, and offsets; changing source metadata/content changes the identity. JSON output is deterministic, contains no runtime timestamps, and unchanged files are not rewritten. Writes replace files atomically.

Each experiment directory contains nine `<document_id>.json` files and a `summary.json`. Summary files include the effective config, full identities, input manifest, corpus statistics, and per-filing statistics. Identical reruns were verified to preserve both bytes and modification times for all 30 output files.

## Corpus results

All nine parsed filings were processed for all three strategies. All 22 tests passed, including the eight existing Phase 2A tests. Coverage checks verify exact text slices, no lost non-whitespace content, complete coverage of all table text, section containment, and unique IDs across the corpus and strategies.

| Strategy | Total chunks | Average characters | Median | Minimum | Maximum | Under 200 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fixed_size | 1,555 | 1,994.19 | 2,000 | 331 | 2,000 | 0 |
| recursive | 1,850 | 1,708.09 | 1,786.0 | 1000 | 2,000 | 0 |
| sec_section | 1,958 | 1,603.56 | 1,744.5 | 39 | 2,000 | 46 |

### Chunks per filing and generated filenames

Each filename below exists once in each of the three experiment directories, for 27 chunk-document files in total. Each contains only chunks from its corresponding source filing.

| Filename | Fixed size | Recursive | SEC section-aware |
| --- | ---: | ---: | ---: |
| AAPL_000032019323000106.json | 118 | 136 | 151 |
| AAPL_000032019324000123.json | 120 | 140 | 150 |
| AAPL_000032019325000079.json | 122 | 143 | 156 |
| MSFT_000095017024087843.json | 214 | 258 | 269 |
| MSFT_000095017025100235.json | 190 | 226 | 237 |
| MSFT_000119312526323660.json | 196 | 233 | 245 |
| NVDA_000104581024000029.json | 197 | 236 | 249 |
| NVDA_000104581025000023.json | 202 | 240 | 252 |
| NVDA_000104581026000021.json | 196 | 238 | 249 |

### Section distribution

Counts indicate chunks intersecting an Item, counted once per Item per chunk. Global strategies can intersect several Items, so these columns are not mutually exclusive. `unsectioned` includes chunks containing any characters outside section spans, including separator whitespace. In the section-aware run its 54 chunks are preamble content. Overlap also increases counts, so these are distribution diagnostics, not retrieval quality scores.

| Item | Fixed size | Recursive | SEC section-aware |
| --- | ---: | ---: | ---: |
| 1 | 212 | 251 | 242 |
| 1A | 434 | 543 | 527 |
| 1B | 12 | 15 | 9 |
| 1C | 35 | 47 | 33 |
| 2 | 13 | 17 | 9 |
| 3 | 17 | 20 | 15 |
| 4 | 9 | 13 | 9 |
| 5 | 27 | 32 | 24 |
| 6 | 9 | 11 | 9 |
| 7 | 190 | 224 | 214 |
| 7A | 24 | 29 | 19 |
| 8 | 336 | 389 | 380 |
| 9 | 10 | 14 | 9 |
| 9A | 33 | 45 | 28 |
| 9B | 16 | 20 | 9 |
| 9C | 10 | 11 | 9 |
| 10 | 18 | 21 | 13 |
| 11 | 12 | 12 | 9 |
| 12 | 10 | 11 | 9 |
| 13 | 9 | 14 | 9 |
| 14 | 12 | 14 | 9 |
| 15 | 256 | 298 | 295 |
| 16 | 21 | 21 | 15 |
| unsectioned | 158 | 196 | 54 |

### Edge cases and distribution checks

- The 46 section-aware chunks below 200 characters exactly match 46 short source sections. They are retained to preserve section boundaries. The minimum is Microsoft’s 39-character Item 6. No extra tiny terminal chunks were introduced in this corpus.
- NVIDIA Item 8 remains a 207-character cross-reference in each filing. Its financial statements remain physically under Item 15, so Item 15 chunk counts are substantial. Chunking preserves the parser’s boundaries rather than relocating referenced content.
- The largest section-aware groups are Item 1A (527 chunks), Item 8 (380), and Item 15 (295). These reflect source lengths and layouts and are not evidence of superior retrieval behavior.
- Fixed-size and recursive runs have 110 and 139 chunks spanning multiple Items, respectively. Section-aware has zero. Mixed chunks carry all intersected section references instead of a misleading single Item.
- Some tables exceed 2,000 characters. Fixed-size, recursive, and section-aware runs have 405, 315, and 309 chunks containing partial tables, respectively. All table characters remain covered and all fragments retain source table references.
- Character windows can split words; heuristic sentence punctuation is not a linguistic tokenizer. Exact overlap may begin mid-sentence or mid-row. Very large overlaps are accepted but can greatly increase chunk counts.
- Empty documents produce zero chunks. Documents without detected sections remain unsectioned; malformed or overlapping source offsets are rejected instead of guessing provenance.

No chunking strategy is claimed to be better. Retrieval performance will be compared in a later phase.

## Files created or changed

- `src/ingestion/chunking.py` — configuration validation, three splitting strategies, source validation, deterministic identities, provenance, table references, statistics, and experiment persistence.
- `scripts/chunk_sec_filings.py` — batch experiment CLI, strategy selection, summaries, and nonzero error exits.
- `configs/chunking.json` — input/output paths and initial experiment parameters for all three strategies.
- `tests/test_chunking.py` — 14 test methods for IDs, provenance, offsets, boundaries, overlap, cross-document isolation, oversized and short sections, natural boundaries, orphan handling, tables, malformed inputs, CLI behavior, statistics, idempotence, and all 27 corpus/strategy combinations.
- `README.md` — Phase 2B commands and link to this report.
- `docs/chunking.md` — this usage guide, output contract, statistics, limitations, and file inventory.
- The 27 JSON documents named above — exact chunk text and metadata for each filing/strategy pair.
- The following three `summary.json` files — experiment manifests plus corpus and per-filing statistics:

- [fixed_size summary](../data/processed/chunks/fixed_size/5d540e6528891489/e0d63ee1453fc40b/summary.json)
- [recursive summary](../data/processed/chunks/recursive/66d0b9a957cc8a2f/e0d63ee1453fc40b/summary.json)
- [sec_section summary](../data/processed/chunks/sec_section/e5f06301c28d0e32/e0d63ee1453fc40b/summary.json)

No additional dependencies were required. Phase 2A source files, metadata, and parsed documents were not modified. No embeddings, retrieval components, model calls, or scoring were added. No Git commit was made.
