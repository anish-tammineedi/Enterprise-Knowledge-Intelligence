from src.agentic.tools import ToolInputError, ToolResult, ToolSpec


def document_tool(retriever, config):
    def execute(payload):
        if not isinstance(payload, dict) or not isinstance(payload.get('query'), str) or not payload['query'].strip():
            raise ToolInputError('query is required')
        mode = payload.get('mode', config.get('mode', 'bm25'))
        top_k = payload.get('top_k', config.get('top_k', 5))
        if mode not in ('bm25', 'hybrid') or type(top_k) is not int or top_k < 1:
            raise ToolInputError('mode or top_k is invalid')
        chunks = retriever.retrieve(payload['query'], mode, top_k)
        evidence = [dict(c) for c in chunks]
        status = 'success' if chunks else 'insufficient_evidence'
        return ToolResult('document_retrieval', status, {'chunks': evidence, 'insufficient': not bool(chunks)}, evidence)
    return ToolSpec('document_retrieval', 'Retrieve ranked chunks from the SEC corpus.',
                    {'type': 'object', 'required': ['query'], 'properties': {'query': {'type': 'string'}, 'mode': {'enum': ['bm25', 'hybrid']}, 'top_k': {'type': 'integer'}}},
                    {'type': 'object', 'required': ['chunks', 'insufficient']}, execute)
