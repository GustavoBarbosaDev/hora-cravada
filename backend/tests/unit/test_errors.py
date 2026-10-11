import json
from collections.abc import AsyncIterator

import pytest
import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.errors import AppError, DependencyUnavailableError
from app.core.logging import configure_logging
from app.main import create_app


class Payload(BaseModel):
    quantity: int


@pytest.fixture
def app() -> FastAPI:
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("detalhe interno que não deve vazar")

    @app.get("/unavailable")
    async def unavailable() -> None:
        raise DependencyUnavailableError("Fila indisponível.", details={"service": "redis"})

    @app.get("/generic")
    async def generic() -> None:
        raise AppError("Falha qualquer.")

    @app.post("/items")
    async def create_item(payload: Payload) -> Payload:
        return payload

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_app_error_uses_its_status_code_and_message(client: AsyncClient) -> None:
    response = await client.get("/unavailable")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "dependency_unavailable"
    assert error["message"] == "Fila indisponível."
    assert error["details"] == {"service": "redis"}


async def test_base_app_error_defaults_to_500(client: AsyncClient) -> None:
    response = await client.get("/generic")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"


async def test_unknown_route_returns_not_found_in_error_format(client: AsyncClient) -> None:
    response = await client.get("/nao-existe")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_invalid_body_lists_each_failing_field(client: AsyncClient) -> None:
    response = await client.post("/items", json={"quantity": "muitos"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["field"] == "body.quantity"


async def test_unexpected_exception_does_not_leak_internal_message(client: AsyncClient) -> None:
    response = await client.get("/boom")

    assert response.status_code == 500
    assert "detalhe interno" not in response.text
    assert response.json()["error"]["code"] == "internal_error"


async def test_request_id_from_header_is_echoed_in_response_and_error_body(
    client: AsyncClient,
) -> None:
    response = await client.get("/generic", headers={"x-request-id": "abc123"})

    assert response.headers["x-request-id"] == "abc123"
    assert response.json()["error"]["request_id"] == "abc123"


async def test_unhandled_exception_response_carries_the_request_id_header(
    client: AsyncClient,
) -> None:
    response = await client.get("/boom", headers={"x-request-id": "abc123"})

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "abc123"
    assert response.json()["error"]["request_id"] == "abc123"


def test_logs_are_emitted_as_json_lines(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.reset_defaults()
    configure_logging("INFO")

    structlog.get_logger().info("reserva_criada", booking_id=7)

    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["event"] == "reserva_criada"
    assert line["booking_id"] == 7
    assert line["level"] == "info"
