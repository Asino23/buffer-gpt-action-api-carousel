# Buffer GPT Action API Carousel

FastAPI facade for GPT Actions and Buffer GraphQL, with support for Instagram carousel media.

## Required environment variables

- `BUFFER_API_KEY`: Buffer API bearer token.
- `CHATGPT_ACTION_SECRET`: shared secret expected in the `X-Action-Secret` header.
- `BUFFER_API_URL`: optional, defaults to `https://api.buffer.com`.

## Deploy on Render

Use this repository as a Web Service. The Dockerfile runs `uvicorn app.main:app` on Render's `PORT`.

After deployment, import `/openapi.json` or the generated OpenAPI YAML into the GPT Action schema.
