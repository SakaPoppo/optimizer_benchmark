from __future__ import annotations

import httpx

from optimizer_benchmark.client import OptimizerClient

from .helpers import minimal_payload, successful_response


def make_client(handler) -> OptimizerClient:
    return OptimizerClient(
        api_url="http://optimizer.test",
        api_key="test-key",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


def test_client_records_success_and_authentication_header() -> None:
    payload = minimal_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "test-key"
        return httpx.Response(200, json=successful_response(payload))

    result = make_client(handler).generate(payload)

    assert result.status == "success"
    assert result.http_status == 200
    assert result.solver_status == "OPTIMAL"
    assert result.elapsed_seconds >= 0


def test_client_records_generation_failure() -> None:
    response = {
        "status": "infeasible",
        "solver_status": "INFEASIBLE",
        "shifts": [],
        "phase_results": [],
        "issues": [{"code": "GENERATION_INFEASIBLE"}],
    }
    result = make_client(lambda _: httpx.Response(200, json=response)).generate(
        minimal_payload()
    )

    assert result.status == "generation_failure"
    assert result.error_type == "generation_failure"
    assert result.response_body == response


def test_client_records_input_error() -> None:
    result = make_client(
        lambda _: httpx.Response(422, json={"detail": {"code": "INVALID"}})
    ).generate(minimal_payload())

    assert result.status == "input_error"
    assert result.http_status == 422
    assert result.error_type == "input_error"


def test_client_records_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = make_client(handler).generate(minimal_payload())

    assert result.status == "connection_error"
    assert result.http_status is None
    assert result.error_type == "connection_error"
