"""Streamable HTTP MCP adapter for the existing Buffer REST bridge.

This service keeps Buffer credentials behind Render and exposes only the
approved EuroIslam publishing tools to an MCP client.
"""

from contextlib import asynccontextmanager
from typing import Any

import hmac
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

from app.config import get_settings
from app.models import (
    BatchScheduledPostRequest,
    PostRequest,
    PublishPostRequest,
    ScheduledPostRequest,
)

mcp = FastMCP(
    "EuroIslam Buffer",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


async def bridge_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    settings = get_settings()
    bridge_url = settings.buffer_bridge_url.rstrip("/")
    headers = {
        "X-Action-Secret": settings.chatgpt_action_secret.get_secret_value(),
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.request(
            method,
            f"{bridge_url}{path}",
            headers=headers,
            params=params,
            json=payload,
        )
    try:
        data = response.json()
    except ValueError:
        data = {"error": {"code": "invalid_bridge_response"}}
    if response.is_error:
        detail = data.get("error", data) if isinstance(data, dict) else data
        raise RuntimeError(f"Buffer bridge error ({response.status_code}): {detail}")
    return data


@mcp.tool()
async def list_channels() -> list[dict[str, str]]:
    """List the connected Buffer channels and their IDs."""
    return await bridge_request("GET", "/channels")


@mcp.tool()
async def list_scheduled_posts(
    channel_id: str | None = None, limit: int = 25
) -> dict[str, Any]:
    """List scheduled Buffer posts, optionally filtered by channel."""
    return await bridge_request(
        "GET",
        "/posts/scheduled",
        params={"channel_id": channel_id, "limit": limit},
    )


@mcp.tool()
async def list_published_posts(
    channel_id: str | None = None, limit: int = 25
) -> dict[str, Any]:
    """List recently published Buffer posts, optionally filtered by channel."""
    return await bridge_request(
        "GET",
        "/posts/published",
        params={"channel_id": channel_id, "limit": limit},
    )


@mcp.tool()
async def create_draft_post(payload: PostRequest) -> dict[str, Any]:
    """Create a Buffer draft without publishing it."""
    return await bridge_request(
        "POST", "/posts/draft", payload=payload.model_dump(mode="json")
    )


@mcp.tool()
async def queue_post(payload: PostRequest) -> dict[str, Any]:
    """Place a post in Buffer's next available queue slot."""
    return await bridge_request(
        "POST", "/posts/queue", payload=payload.model_dump(mode="json")
    )


@mcp.tool()
async def schedule_post(payload: ScheduledPostRequest) -> dict[str, Any]:
    """Schedule one post or X thread at the supplied ISO 8601 time."""
    return await bridge_request(
        "POST", "/posts/schedule", payload=payload.model_dump(mode="json")
    )


@mcp.tool()
async def schedule_posts_batch(payload: BatchScheduledPostRequest) -> dict[str, Any]:
    """Schedule between one and twenty posts and return per-item results."""
    return await bridge_request(
        "POST", "/posts/schedule/batch", payload=payload.model_dump(mode="json")
    )


@mcp.tool()
async def publish_post_now(payload: PublishPostRequest) -> dict[str, Any]:
    """Publish immediately; confirm_publish must be true."""
    return await bridge_request(
        "POST", "/posts/publish", payload=payload.model_dump(mode="json")
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="EuroIslam Buffer MCP", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def require_mcp_token(request: Request, call_next):
    if request.url.path.startswith("/mcp"):
        settings = get_settings()
        configured = settings.mcp_auth_token or settings.chatgpt_action_secret
        expected = configured.get_secret_value()
        supplied = request.headers.get("authorization", "")
        token = supplied.removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(token, expected):
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_mcp_credentials"},
            )
    return await call_next(request)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/mcp", mcp.streamable_http_app())
