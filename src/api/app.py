from contextlib import asynccontextmanager
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import re
import time

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.models import (ApiErrorBody, ApiErrorResponse, HealthResponse, QueryRequest,
                            QueryResponse, ReadyResponse, RetrieveRequest, RetrieveResponse)
from src.api.runtime import Runtime, ServiceFailure
from src.api.settings import Settings
from src.observability.trace import Privacy, validate_trace


TRACE_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')


def create_app(settings=None, runtime_factory=Runtime):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.executor = ThreadPoolExecutor(max_workers=settings.max_concurrency,
                                                thread_name_prefix='eki-service')
        app.state.slots = asyncio.Semaphore(settings.max_concurrency)
        app.state.runtime = runtime_factory(settings)
        yield
        app.state.executor.shutdown(wait=False, cancel_futures=True)

    api = FastAPI(title='Enterprise Knowledge Intelligence API', version='1.0.0', lifespan=lifespan)
    api.state.settings = settings

    @api.exception_handler(ServiceFailure)
    async def service_failure_handler(request, exc):
        return JSONResponse(status_code=exc.status_code,
            content=ApiErrorResponse(error=ApiErrorBody(code=exc.code, message=exc.message)).model_dump())

    @api.exception_handler(RequestValidationError)
    async def invalid_request_handler(request, exc):
        return JSONResponse(status_code=422,
            content=ApiErrorResponse(error=ApiErrorBody(code='invalid_request', message='Request fields are invalid')).model_dump())

    @api.exception_handler(Exception)
    async def internal_error_handler(request, exc):
        return JSONResponse(status_code=500,
            content=ApiErrorResponse(error=ApiErrorBody(code='internal_failure', message='Request could not be completed')).model_dump())

    def release_slot(loop, slots):
        try:
            loop.call_soon_threadsafe(slots.release)
        except RuntimeError:
            pass

    async def bounded(function):
        slots = api.state.slots
        try:
            await asyncio.wait_for(slots.acquire(), timeout=min(5.0, settings.request_timeout_seconds))
        except asyncio.TimeoutError:
            raise ServiceFailure(503, 'service_busy', 'Service concurrency limit reached') from None
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(api.state.executor, function)
        future.add_done_callback(lambda _: release_slot(loop, slots))
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=settings.request_timeout_seconds)
        except asyncio.TimeoutError:
            raise ServiceFailure(504, 'timeout', 'Request timed out') from None

    @api.get('/health', response_model=HealthResponse)
    async def health():
        return {'status': 'ok'}

    @api.get('/ready', response_model=ReadyResponse)
    async def ready():
        return await bounded(api.state.runtime.readiness)

    @api.post('/retrieve', response_model=RetrieveResponse,
              responses={422: {'model': ApiErrorResponse}, 503: {'model': ApiErrorResponse}, 504: {'model': ApiErrorResponse}})
    async def retrieve(payload: RetrieveRequest):
        started = time.perf_counter()
        result = await bounded(lambda: api.state.runtime.retrieve(payload.query, payload.mode, payload.top_k))
        evidence = []
        for row in result.evidence:
            evidence.append({'context_id': None, 'rank': row.get('retrieval_rank'),
                'score': row.get('retrieval_score'), 'chunk_id': row['chunk_id'],
                'document_id': row['document_id'], 'ticker': row['ticker'],
                'company': row['company'], 'cik': row['cik'], 'form': row['form'],
                'filing_date': row['filing_date'], 'report_date': row['report_date'],
                'accession_number': row['accession_number'], 'item': row.get('item'),
                'section_id': row['section_id'], 'section_name': row['section_name'],
                'source_url': row['source_url'], 'start_char': row['start_char'],
                'end_char': row['end_char'], 'text': row['text']})
        return {'query': payload.query, 'mode': payload.mode or settings.retrieval_mode,
                'top_k': payload.top_k or settings.retrieval_top_k, 'evidence': evidence,
                'latency_seconds': time.perf_counter() - started}

    @api.post('/query', response_model=QueryResponse,
              responses={422: {'model': ApiErrorResponse}, 502: {'model': ApiErrorResponse},
                         503: {'model': ApiErrorResponse}, 504: {'model': ApiErrorResponse}})
    async def query(payload: QueryRequest):
        trace_id = __import__('uuid').uuid4().hex
        trace, answer, contexts, citations = await bounded(
            lambda: api.state.runtime.run_query(payload.query, trace_id))
        categories = trace['failure_attribution']['categories']
        if 'generation_failure' in categories:
            error = trace['lower_level'].get('error') or {}
            if error.get('code') == 'timeout':
                raise ServiceFailure(504, 'timeout', 'Generation timed out')
            raise ServiceFailure(503, 'generation_backend_unavailable', 'Generation backend is unavailable')
        if any(tool['status'] in ('error', 'invalid_input') for tool in trace['tools']):
            raise ServiceFailure(503, 'tool_failure', 'A requested tool could not complete')
        if 'invalid_output' in categories or 'citation_failure' in categories:
            raise ServiceFailure(502, 'invalid_output', 'Generation output failed validation')
        if answer is None:
            raise ServiceFailure(500, 'internal_failure', 'Request could not be completed')
        selected = trace['routing']['tools_selected'] or []
        docs = [c for c in contexts if not c['chunk_id'].startswith('financial:')]
        elapsed = trace['latency']['end_to_end_seconds']
        return {'trace_id': trace_id, 'answer': answer['answer'], 'abstained': answer['abstained'],
                'citations': citations, 'evidence': docs, 'routing_decision': trace['routing']['decision'],
                'routing_reason': trace['routing']['reason'], 'tools_used': selected,
                'validation_status': trace['result']['validation_status'],
                'status': trace['failure_attribution']['primary'],
                'latency': {'end_to_end_seconds': elapsed,
                            'generation_seconds': trace['generation']['latency_seconds'],
                            'retrieval_seconds': trace['retrieval']['latency_seconds']}}

    @api.get('/trace/{trace_id}', responses={404: {'model': ApiErrorResponse}, 422: {'model': ApiErrorResponse}})
    async def get_trace(trace_id: str):
        if not TRACE_ID.fullmatch(trace_id):
            raise ServiceFailure(422, 'invalid_request', 'Trace identifier is invalid')
        path = settings.trace_dir / (trace_id + '.json')
        if not path.is_file():
            raise ServiceFailure(404, 'trace_not_found', 'Trace was not found')
        try:
            trace = json.loads(path.read_text(encoding='utf-8'))
            validate_trace(trace)
            if trace['trace_id'] != trace_id:
                raise ValueError()
            return Privacy().clean(trace)
        except Exception:
            raise ServiceFailure(500, 'internal_failure', 'Saved trace is unavailable') from None

    return api


app = create_app()
