"""optimizer APIへの認証付きHTTP通信と外部応答時間の計測。"""

from __future__ import annotations

import time

import httpx

from .models import ApiCallResult


class OptimizerClient:
    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.endpoint = f"{api_url.rstrip('/')}/generate"
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def generate(self, payload: dict) -> ApiCallResult:
        started_at = time.perf_counter()
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(self.endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as error:
            return self._request_error(started_at, "timeout", error)
        except httpx.RequestError as error:
            return self._request_error(started_at, "connection_error", error)

        elapsed_seconds = time.perf_counter() - started_at
        try:
            body = response.json()
        except ValueError:
            return ApiCallResult(
                status="invalid_response",
                elapsed_seconds=elapsed_seconds,
                http_status=response.status_code,
                error_type="invalid_response",
                error_message="API応答をJSONとして読み取れませんでした。",
            )
        if not isinstance(body, dict):
            return ApiCallResult(
                status="invalid_response",
                elapsed_seconds=elapsed_seconds,
                http_status=response.status_code,
                error_type="invalid_response",
                error_message="API応答のJSONルートがオブジェクトではありません。",
            )
        if response.status_code == 422:
            return ApiCallResult(
                status="input_error",
                elapsed_seconds=elapsed_seconds,
                http_status=response.status_code,
                response_body=body,
                error_type="input_error",
                error_message="optimizer APIが入力エラーを返しました。",
            )
        if not response.is_success:
            return ApiCallResult(
                status="http_error",
                elapsed_seconds=elapsed_seconds,
                http_status=response.status_code,
                response_body=body,
                error_type="http_error",
                error_message=f"optimizer APIがHTTP {response.status_code}を返しました。",
            )
        if body.get("status") != "success":
            return ApiCallResult(
                status="generation_failure",
                elapsed_seconds=elapsed_seconds,
                http_status=response.status_code,
                response_body=body,
                error_type="generation_failure",
                error_message="optimizer APIはシフトを生成できませんでした。",
            )
        return ApiCallResult(
            status="success",
            elapsed_seconds=elapsed_seconds,
            http_status=response.status_code,
            response_body=body,
        )

    @staticmethod
    def _request_error(
        started_at: float,
        error_type: str,
        error: httpx.RequestError,
    ) -> ApiCallResult:
        return ApiCallResult(
            status=error_type,
            elapsed_seconds=time.perf_counter() - started_at,
            error_type=error_type,
            error_message=str(error),
        )
