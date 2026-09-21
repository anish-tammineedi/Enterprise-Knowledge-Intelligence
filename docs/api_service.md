# Enterprise Knowledge Intelligence API

The API wraps the existing SEC section retriever, deterministic agentic router, local Company Facts cache, grounded prompt, Ollama provider, and Phase 6 trace writer. Retrieval, tool work, and synchronous model calls run in a bounded thread pool so they do not block FastAPI's event loop. No service starts Ollama.

## Local setup

Use Python 3.11 and install the project requirements:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
set -a && . ./.env && set +a
.venv/bin/python -m src.api
```

`.env` is a local shell configuration example; the app reads environment variables from its process and does not parse a dotenv file. Defaults bind only to `127.0.0.1:8000`, use BM25 top five, the repository's Ollama model/base URL, a 120 second request timeout, four worker slots, and `data/processed/service_traces`.

The saved document chunks/index and three normalized financial caches are needed for `/ready` and query functionality. The normal Phase 2–5 project artifacts supply them. The ready endpoint checks document component construction and accepted financial-cache coverage; Ollama is optional, so it can report unavailable while the service remains ready. `/health` only confirms that the HTTP process responds.

## Endpoints

Interactive OpenAPI documentation is available at `/docs`.

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready
curl -s -X POST http://127.0.0.1:8000/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query":"Apple fiscal 2025 revenue","mode":"bm25","top_k":3}'
curl -s -X POST http://127.0.0.1:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"What was Apple revenue in fiscal 2025?"}'
curl -s http://127.0.0.1:8000/trace/TRACE_ID
```

`/query` returns a typed answer, abstention flag, validated citations, evidence, route, tools, validation state, trace ID, and latency metadata. Unsupported patterns return the existing canonical abstention with `status: unsupported_query` and make no model call. `/retrieve` applies BM25 or hybrid mode and top-k without generation. `/trace/{trace_id}` only serves saved Phase 6 schema traces and rejects unsafe IDs.

Errors use a stable `{error:{code,message,trace_id}}` shape. Invalid requests return 422; missing local artifacts and tool failures return 503; invalid model output returns 502; generation/request timeout returns 504; unexpected errors return a generic 500. Error responses contain no exception details or configuration values.

## Configuration

`.env.example` lists supported environment variables. Prefix: `EKI_`.

- `EKI_HOST`, `EKI_PORT`
- `EKI_RETRIEVAL_MODE` (`bm25` or `hybrid`), `EKI_RETRIEVAL_TOP_K`
- `EKI_OLLAMA_BASE_URL`, `EKI_OLLAMA_MODEL`, `EKI_PROVIDER` (`ollama`)
- `EKI_REQUEST_TIMEOUT_SECONDS`, `EKI_MAX_CONCURRENCY`
- `EKI_TRACE_DIR`

Values are range-checked; model, API credentials, and SEC User-Agent are never returned by the API. The Ollama adapter requires a loopback HTTP endpoint, matching its existing local-only security rule.

## Ollama

Install and start Ollama separately, then install the configured model:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
export EKI_OLLAMA_BASE_URL=http://127.0.0.1:11434
export EKI_OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M
```

For a local API process the default URL is `http://127.0.0.1:11434`. Readiness checks `/api/tags` with a short loopback request; it never generates text. The configured model must already be installed. There is no model download path in the API or container build.

The container can share the host network on Linux to reach a host Ollama at loopback:

```bash
docker run --network host \
  -e EKI_HOST=127.0.0.1 -e EKI_PORT=8000 \
  -e EKI_OLLAMA_BASE_URL=http://127.0.0.1:11434 \
  eki-api:local
```

The app's existing Ollama provider intentionally rejects non-loopback endpoints. Docker deployments without host networking can use an SSH local forward that exposes the external Ollama endpoint on the container host's loopback. The Ollama process remains separate.

## Docker

```bash
docker build -t eki-api:local .
docker run --rm -p 8000:8000 \
  -v "$PWD/configs:/app/configs:ro" \
  -v "$PWD/data:/app/data:ro" \
  -v "$PWD/evals/results:/app/evals/results:ro" \
  -v eki-traces:/var/lib/eki/traces \
  eki-api:local
```

The image uses a fixed Python 3.11 patch base, installs the project's bounded dependency set, copies no corpora or secrets, runs as UID 10001, and includes a `/health` check. Mount the local corpus, retrieval results/index, and financial cache read-only at the matching paths. Trace files go to the named writable volume. Builds do not install or download the Qwen model. The existing broad dependency ranges are not a full transitive lockfile; deployments that require bit-for-bit dependency resolution should build from a separately reviewed lock.

## Caching and concurrency

The service reuses the existing parsed/chunk, retrieval embedding/index, query embedding, and SEC fact files. It does not add Redis, write embeddings, or keep a duplicate answer cache. The document retriever and fact store are loaded lazily once per process and reused. Restart the process after changing corpus/index/cache files; no file watcher or live cache invalidation is provided. Persisted traces are per request and do not cache answers.

Synchronous retrieval/tools/provider calls use a bounded thread pool with matching concurrency permits. API admission waits up to five seconds and each request has the configured wall timeout. Existing provider request timeouts are capped by that setting. Python cannot forcibly stop a synchronous worker already in progress after the HTTP timeout, so its concurrency slot remains occupied until it exits; the bounded pool prevents unbounded worker creation. Worker cancellation does not interrupt CPU-bound model code.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

FastAPI tests use mocked tools/providers and an in-process ASGI client. CI runs the offline suite on Python 3.11; it does not start Ollama, download models, or fetch SEC data. Corpus-backed integration checks run when the ignored local corpus is present and skip with an explicit reason in a clean checkout without that corpus.

## Limits

The router remains the Phase 5 deterministic rule set. Generation remains the existing grounded Ollama adapter and requires a configured local Ollama service. The service is a single-process local API with in-process concurrency controls and trace files; it has no authentication, rate limiting, distributed queue, multi-process trace lock, or external monitoring. Hybrid retrieval still depends on the existing locally cached embedding model and index. Readiness treats Ollama as optional and does not make the liveness endpoint depend on it.
