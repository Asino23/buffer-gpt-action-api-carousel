# Buffer GPT Action API Carousel

FastAPI facade for GPT Actions and Buffer GraphQL, with support for Instagram carousel media and a Streamable HTTP MCP adapter.

## Required environment variables

- `BUFFER_API_KEY`: Buffer API bearer token.
- `CHATGPT_ACTION_SECRET`: shared secret expected in the `X-Action-Secret` header and used by the MCP adapter as a fallback bearer token.
- `BUFFER_API_URL`: optional, defaults to `https://api.buffer.com`.
- `BUFFER_BRIDGE_URL`: optional, defaults to the existing EuroIslam Render REST bridge.
- `MCP_AUTH_TOKEN`: optional separate bearer token for MCP clients; if omitted, `CHATGPT_ACTION_SECRET` is used.

## REST deployment on Render

Use this repository as a Web Service. The Dockerfile runs `uvicorn app.main:app` on Render's `PORT`.

After deployment, import `/openapi.json` or the generated OpenAPI YAML into the GPT Action schema.

## MCP deployment on Render

Create a second Web Service from this same repository so the existing REST service remains unchanged.

- Runtime: Docker
- Start command: `uvicorn app.mcp_server:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`
- Health check path: `/healthz`
- MCP endpoint: `/mcp`
- Set the same `BUFFER_API_KEY` and `CHATGPT_ACTION_SECRET` used by the REST service.
- Set `BUFFER_BRIDGE_URL` to the live REST bridge URL when it differs from the default.
- Prefer setting a distinct `MCP_AUTH_TOKEN`; never commit any secret to GitHub.

The MCP adapter exposes channels, scheduled and published post reads, drafts, queueing, single scheduling, batch scheduling, and immediate publishing. Publishing remains protected by the payload confirmation field and should be confirmed in the client before execution.
