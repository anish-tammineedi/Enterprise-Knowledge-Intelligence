from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class QueryRequest(RequestModel):
    query: str = Field(min_length=1, max_length=12000)


class RetrieveRequest(RequestModel):
    query: str = Field(min_length=1, max_length=12000)
    top_k: int | None = Field(default=None, ge=1, le=100)
    mode: Literal['bm25', 'hybrid'] | None = None


class Citation(BaseModel):
    context_id: str
    chunk_id: str
    document_id: str
    ticker: str
    accession_number: str
    source_url: str


class Evidence(BaseModel):
    context_id: str | None = None
    rank: int | None = None
    score: float | None = None
    chunk_id: str
    document_id: str
    ticker: str
    company: str
    cik: str
    form: str
    filing_date: str
    report_date: str
    accession_number: str
    item: str | None = None
    section_id: str
    section_name: str
    source_url: str
    start_char: int
    end_char: int
    text: str


class QueryResponse(BaseModel):
    trace_id: str
    answer: str
    abstained: bool
    citations: list[Citation]
    evidence: list[Evidence]
    routing_decision: str
    routing_reason: str
    tools_used: list[str]
    validation_status: Literal['passed', 'failed']
    status: str
    latency: dict[str, float | None]


class RetrieveResponse(BaseModel):
    query: str
    mode: str
    top_k: int
    evidence: list[Evidence]
    latency_seconds: float


class ApiErrorBody(BaseModel):
    code: str
    message: str
    trace_id: str | None = None


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody


class HealthResponse(BaseModel):
    status: Literal['ok']


class ReadyResponse(BaseModel):
    status: Literal['ready', 'not_ready']
    components: dict[str, dict[str, Any]]
