"""Small ASGI test client wrapper compatible with the installed httpx."""

import asyncio
from typing import Any

import httpx


def api_request(app, method: str, path: str, **kwargs: Any) -> httpx.Response:
    async def _request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(_request())
