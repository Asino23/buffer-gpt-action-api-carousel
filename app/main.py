import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated, AsyncIterator
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.buffer import BufferClient, BufferError
from app.config import Settings, get_settings
from app.models import (
    BatchPostResult,
    BatchScheduledPostRequest,
    BatchScheduleResult,
    Channel,
    PostRequest,
    PostResult,
    PublishPostRequest,
    ScheduledPostRequest,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger("buffer_action_api")
ROME = ZoneInfo("Europe/Rome")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.buffer = BufferClient(
        settings.buffer_api_key.get_secret_value(), settings.buffer_api_url
    )
    yield


app = FastAPI(
    title="Buffer GPT Action API",
    version="1.4.0",
    description=(
        "Secure REST facade over Buffer's official GraphQL API, including "
        "Instagram carousel media."
    ),
    lifespan=lifespan,
)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def settings_for(request: Request) -> Settings:
    return request.app.state.settings


def buffer_for(request: Request) -> BufferClient:
    return request.app.state.buffer


async def authenticate(
    settings: Annotated[Settings, Depends(settings_for)],
    x_action_secret: Annotated[
        str | None, Header(alias="X-Action-Secret")
    ] = None,
) -> None:
    expected = settings.chatgpt_action_secret.get_secret_value()
    if x_action_secret is None or not hmac.compare_digest(x_action_secret, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials"
        )


Buffer = Annotated[BufferClient, Depends(buffer_for)]


@app.exception_handler(BufferError)
async def buffer_error_handler(request: Request, exc: BufferError) -> JSONResponse:
    logger.warning("buffer_request_failed path=%s code=%s", request.url.path, exc.code)
    return JSONResponse(
        status_code=exc.status_code, content={"error": {"code": exc.code}}
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.info("request_validation_failed path=%s", request.url.path)
    errors = [
        {
            "field": ".".join(map(str, error["loc"][1:])),
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "validation_error", "details": errors}},
    )


async def post_input(
    payload: PostRequest,
    client: BufferClient,
    *,
    mode: str,
    draft: bool = False,
    channels: list[dict[str, str]] | None = None,
) -> dict:
    available_channels = channels if channels is not None else await client.channels()
    channel = next(
        (
            item
            for item in available_channels
            if item["channel_id"] == payload.channel_id
        ),
        None,
    )
    if channel is None:
        raise HTTPException(status_code=422, detail="invalid_channel_id")

    platform = channel["platform"].lower()
    value: dict = {
        "channelId": payload.channel_id,
        "text": payload.text,
        "schedulingType": "automatic",
        "mode": mode,
    }
    if payload.thread is not None:
        if platform not in {"twitter", "x", "twitter/x"}:
            raise HTTPException(
                status_code=422, detail="thread_requires_twitter_channel"
            )
        value["metadata"] = {
            "twitter": {"thread": [{"text": item} for item in payload.thread]}
        }
    elif platform == "facebook":
        value["metadata"] = {"facebook": {"type": "post"}}
    elif platform == "instagram":
        if payload.image_url is None and payload.image_urls is None:
            raise HTTPException(status_code=422, detail="instagram_image_required")
        value["metadata"] = {
            "instagram": {"type": "post", "shouldShareToFeed": True}
        }
    if draft:
        value["saveToDraft"] = True
    image_urls = payload.image_urls or (
        [payload.image_url] if payload.image_url else []
    )
    if image_urls:
        assets = []
        for index, image_url in enumerate(image_urls):
            image: dict = {"url": str(image_url)}
            alt_text = None
            if payload.alt_texts:
                alt_text = (
                    payload.alt_texts[index]
                    if len(payload.alt_texts) > 1
                    else payload.alt_texts[0]
                )
            elif payload.alt_text is not None:
                alt_text = payload.alt_text
            if alt_text is not None:
                image["metadata"] = {"altText": alt_text}
            assets.append({"image": image})
        value["assets"] = assets
    return value


async def create(client: BufferClient, value: dict) -> PostResult:
    post = await client.create_post(value)
    return PostResult(
        id=post["id"], text=post.get("text"), due_at=post.get("dueAt")
    )


def normalized_schedule(payload: ScheduledPostRequest) -> datetime:
    scheduled = payload.scheduled_at
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=ROME)
    if scheduled.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=422, detail="scheduled_at_must_be_in_the_future"
        )
    return scheduled


async def schedule_one(
    payload: ScheduledPostRequest,
    client: BufferClient,
    *,
    channels: list[dict[str, str]] | None = None,
) -> PostResult:
    scheduled = normalized_schedule(payload)
    value = await post_input(
        payload, client, mode="customScheduled", channels=channels
    )
    value["dueAt"] = scheduled.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    return await create(client, value)


@app.get(
    "/channels",
    response_model=list[Channel],
    dependencies=[Depends(authenticate)],
    operation_id="listChannels",
)
async def list_channels(client: Buffer) -> list[Channel]:
    return [Channel.model_validate(channel) for channel in await client.channels()]


@app.post(
    "/posts/draft",
    response_model=PostResult,
    status_code=201,
    dependencies=[Depends(authenticate)],
    operation_id="createDraftPost",
)
async def draft(payload: PostRequest, client: Buffer) -> PostResult:
    return await create(
        client, await post_input(payload, client, mode="addToQueue", draft=True)
    )


@app.post(
    "/posts/queue",
    response_model=PostResult,
    status_code=201,
    dependencies=[Depends(authenticate)],
    operation_id="queuePost",
)
async def queue(payload: PostRequest, client: Buffer) -> PostResult:
    return await create(client, await post_input(payload, client, mode="addToQueue"))


@app.post(
    "/posts/schedule",
    response_model=PostResult,
    status_code=201,
    dependencies=[Depends(authenticate)],
    operation_id="schedulePost",
)
async def schedule(payload: ScheduledPostRequest, client: Buffer) -> PostResult:
    return await schedule_one(payload, client)


@app.post(
    "/posts/schedule/batch",
    response_model=BatchScheduleResult,
    status_code=200,
    dependencies=[Depends(authenticate)],
    operation_id="schedulePostsBatch",
)
async def schedule_batch(
    payload: BatchScheduledPostRequest, client: Buffer
) -> BatchScheduleResult:
    channels = await client.channels()
    results: list[BatchPostResult] = []
    for index, post in enumerate(payload.posts):
        try:
            created = await schedule_one(post, client, channels=channels)
            results.append(
                BatchPostResult(
                    index=index,
                    channel_id=post.channel_id,
                    scheduled_at=post.scheduled_at,
                    success=True,
                    id=created.id,
                )
            )
        except HTTPException as exc:
            results.append(
                BatchPostResult(
                    index=index,
                    channel_id=post.channel_id,
                    scheduled_at=post.scheduled_at,
                    success=False,
                    error=str(exc.detail),
                )
            )
        except BufferError as exc:
            results.append(
                BatchPostResult(
                    index=index,
                    channel_id=post.channel_id,
                    scheduled_at=post.scheduled_at,
                    success=False,
                    error=exc.code,
                )
            )

    success_count = sum(item.success for item in results)
    return BatchScheduleResult(
        success_count=success_count,
        failure_count=len(results) - success_count,
        results=results,
    )


@app.post(
    "/posts/publish",
    response_model=PostResult,
    status_code=201,
    dependencies=[Depends(authenticate)],
    operation_id="publishPostNow",
)
async def publish(payload: PublishPostRequest, client: Buffer) -> PostResult:
    return await create(client, await post_input(payload, client, mode="shareNow"))
