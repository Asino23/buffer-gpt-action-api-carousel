from typing import Any

import httpx


ORGANIZATIONS_QUERY = """
query GetOrganizations {
  account { organizations { id } }
}
"""

CHANNELS_QUERY = """
query GetChannels($input: ChannelsInput!) {
  channels(input: $input) { id name service }
}
"""

CREATE_POST_MUTATION = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id text dueAt } }
    ... on MutationError { message }
  }
}
"""


class BufferError(Exception):
    def __init__(self, code: str, *, status_code: int = 502):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class BufferClient:
    def __init__(self, api_key: str, api_url: str, client: httpx.AsyncClient | None = None):
        self._api_key = api_key
        self._api_url = api_url
        self._client = client

    async def request(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0)
        )
        try:
            response = await client.post(
                self._api_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "variables": variables or {}},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BufferError("buffer_unavailable") from exc
        finally:
            if owns_client:
                await client.aclose()

        errors = payload.get("errors")
        if errors:
            code = errors[0].get("extensions", {}).get("code", "BUFFER_ERROR")
            status = {
                "UNAUTHORIZED": 502,
                "FORBIDDEN": 502,
                "NOT_FOUND": 404,
                "RATE_LIMIT_EXCEEDED": 429,
            }.get(code, 502)
            raise BufferError(f"buffer_{str(code).lower()}", status_code=status)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise BufferError("invalid_buffer_response")
        return data

    async def channels(self) -> list[dict[str, str]]:
        organizations = (await self.request(ORGANIZATIONS_QUERY))["account"][
            "organizations"
        ]
        channels: dict[str, dict[str, str]] = {}
        for organization in organizations:
            result = await self.request(
                CHANNELS_QUERY, {"input": {"organizationId": organization["id"]}}
            )
            for channel in result["channels"]:
                channels[channel["id"]] = {
                    "name": channel["name"],
                    "platform": channel["service"],
                    "channel_id": channel["id"],
                }
        return list(channels.values())

    async def create_post(self, post_input: dict[str, Any]) -> dict[str, Any]:
        result = (
            await self.request(CREATE_POST_MUTATION, {"input": post_input})
        )["createPost"]
        if "post" not in result:
            raise BufferError("buffer_rejected_post", status_code=422)
        return result["post"]
