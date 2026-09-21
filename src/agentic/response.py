from src.generation.contracts import Question
from src.generation.grounding import build_context, build_prompt, validate_citation_grounding, validate_output


def evidence_contexts(trace):
    chunks = []
    for result in trace.get('tool_results', []):
        if result['tool_name'] == 'document_retrieval':
            chunks.extend(result.get('evidence', []))
        elif result['tool_name'] == 'financial_data' and result['status'] == 'success':
            row = result['evidence'][0]
            text = f"{row['ticker']} fiscal {row['fiscal_year']} {row['metric']}: {row['value']} {row.get('unit', row.get('units'))}"
            chunks.append({'chunk_id': 'financial:' + row['ticker'] + ':' + str(row['fiscal_year']) + ':' + row['metric'],
                           'document_id': row.get('document_id', 'financial_data'), 'source_document_id': row.get('document_id', 'financial_data'),
                           'company': row.get('company', row['ticker']), 'ticker': row['ticker'], 'cik': row.get('cik', ''), 'form': '10-K',
                           'filing_date': row.get('filing_date', str(row['fiscal_year']) + '-01-01'), 'report_date': row.get('report_date', row.get('end', str(row['fiscal_year']) + '-01-01')),
                           'accession_number': row.get('accession_number', ''), 'item': row.get('item'), 'section_id': row.get('section_id', 'financial_data'),
                           'section_name': row.get('section_name', 'Structured SEC financial data'), 'sections': [{'section_id': row.get('section_id', 'financial_data')}],
                           'source_url': row.get('source_url', ''), 'start_char': 0, 'end_char': len(text), 'text': text})
    return build_context(chunks)


def build_orchestrated_prompt(query, trace, config):
    contexts = evidence_contexts(trace)
    return build_prompt(Question('orchestrated', query), contexts, config), contexts


def validate_orchestrated_output(output, contexts, retrieved_chunks):
    parsed = validate_output(output, contexts)
    validate_citation_grounding(parsed, contexts, retrieved_chunks)
    return parsed
