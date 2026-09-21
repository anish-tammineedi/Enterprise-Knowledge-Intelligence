from dataclasses import dataclass
from typing import Any, Callable
import time


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    status: str
    output: dict
    evidence: list[dict]
    error: dict | None = None
    latency_seconds: float = 0.0


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    execute: Callable[[dict], ToolResult]


class ToolInputError(ValueError):
    pass


def execute_tool(spec, payload):
    started = time.perf_counter()
    try:
        result = spec.execute(payload)
        if not isinstance(result, ToolResult):
            raise TypeError('Tool returned invalid result')
        return ToolResult(spec.name, result.status, result.output, result.evidence, result.error,
                          time.perf_counter() - started)
    except ToolInputError as exc:
        return ToolResult(spec.name, 'invalid_input', {}, [], {'code': 'invalid_input', 'detail': str(exc)},
                          time.perf_counter() - started)
    except Exception:
        return ToolResult(spec.name, 'error', {}, [], {'code': 'tool_execution_error'}, time.perf_counter() - started)
