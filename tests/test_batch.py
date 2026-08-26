from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.buffer import BufferError
from app.main import schedule_batch
from app.models import BatchScheduledPostRequest, ScheduledPostRequest


class FakeBufferClient:
    def __init__(self, *, fail_channel: str | None = None):
        self.fail_channel = fail_channel
        self.created: list[dict] = []
        self.channel_reads = 0

    async def channels(self) -> list[dict[str, str]]:
        self.channel_reads += 1
        return [
            {
                "name": "euroislam.eu",
                "platform": "instagram",
                "channel_id": "instagram-id",
            },
            {
                "name": "EuroIslam",
                "platform": "facebook",
                "channel_id": "facebook-id",
            },
        ]

    async def create_post(self, post_input: dict) -> dict:
        if post_input["channelId"] == self.fail_channel:
            raise BufferError("buffer_rejected_post", status_code=422)
        self.created.append(post_input)
        return {
            "id": f"post-{len(self.created)}",
            "text": post_input["text"],
            "dueAt": post_input["dueAt"],
        }


def future_time(hours: int = 1) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


@pytest.mark.asyncio
async def test_batch_schedules_all_posts_with_one_channel_lookup() -> None:
    client = FakeBufferClient()
    payload = BatchScheduledPostRequest(
        posts=[
            ScheduledPostRequest(
                channel_id="instagram-id",
                text="Instagram post",
                image_url="https://example.com/image.jpg",
                scheduled_at=future_time(1),
            ),
            ScheduledPostRequest(
                channel_id="facebook-id",
                text="Facebook post",
                scheduled_at=future_time(2),
            ),
        ]
    )

    result = await schedule_batch(payload, client)  # type: ignore[arg-type]

    assert result.success_count == 2
    assert result.failure_count == 0
    assert [item.id for item in result.results] == ["post-1", "post-2"]
    assert client.channel_reads == 1
    assert client.created[0]["metadata"]["instagram"]["type"] == "post"
    assert client.created[1]["metadata"]["facebook"]["type"] == "post"


@pytest.mark.asyncio
async def test_batch_reports_partial_failure_and_continues() -> None:
    client = FakeBufferClient(fail_channel="facebook-id")
    payload = BatchScheduledPostRequest(
        posts=[
            ScheduledPostRequest(
                channel_id="facebook-id",
                text="Fails",
                scheduled_at=future_time(1),
            ),
            ScheduledPostRequest(
                channel_id="instagram-id",
                text="Succeeds",
                image_url="https://example.com/image.jpg",
                scheduled_at=future_time(2),
            ),
        ]
    )

    result = await schedule_batch(payload, client)  # type: ignore[arg-type]

    assert result.success_count == 1
    assert result.failure_count == 1
    assert result.results[0].error == "buffer_rejected_post"
    assert result.results[1].success is True


@pytest.mark.asyncio
async def test_batch_reports_invalid_channel_without_stopping() -> None:
    client = FakeBufferClient()
    payload = BatchScheduledPostRequest(
        posts=[
            ScheduledPostRequest(
                channel_id="missing-id",
                text="Invalid channel",
                scheduled_at=future_time(1),
            ),
            ScheduledPostRequest(
                channel_id="facebook-id",
                text="Valid channel",
                scheduled_at=future_time(2),
            ),
        ]
    )

    result = await schedule_batch(payload, client)  # type: ignore[arg-type]

    assert result.failure_count == 1
    assert result.results[0].error == "invalid_channel_id"
    assert result.results[1].success is True


@pytest.mark.asyncio
async def test_instagram_carousel_uses_ordered_assets_and_alt_texts() -> None:
    client = FakeBufferClient()
    payload = BatchScheduledPostRequest(
        posts=[
            ScheduledPostRequest(
                channel_id="instagram-id",
                text="Carousel post",
                image_urls=[
                    "https://example.com/slide-01.jpg",
                    "https://example.com/slide-02.jpg",
                    "https://example.com/slide-03.jpg",
                ],
                alt_texts=["Alt 1", "Alt 2", "Alt 3"],
                scheduled_at=future_time(1),
            )
        ]
    )

    result = await schedule_batch(payload, client)  # type: ignore[arg-type]

    assert result.success_count == 1
    assert client.created[0]["metadata"]["instagram"]["type"] == "post"
    assert client.created[0]["assets"] == [
        {
            "image": {
                "url": "https://example.com/slide-01.jpg",
                "metadata": {"altText": "Alt 1"},
            }
        },
        {
            "image": {
                "url": "https://example.com/slide-02.jpg",
                "metadata": {"altText": "Alt 2"},
            }
        },
        {
            "image": {
                "url": "https://example.com/slide-03.jpg",
                "metadata": {"altText": "Alt 3"},
            }
        },
    ]


def test_batch_rejects_more_than_twenty_posts() -> None:
    with pytest.raises(ValueError):
        BatchScheduledPostRequest(
            posts=[
                ScheduledPostRequest(
                    channel_id="facebook-id",
                    text=f"Post {index}",
                    scheduled_at=future_time(index + 1),
                )
                for index in range(21)
            ]
        )
